"""
tests/test_bleed_subtract.py — proves src/bleed_subtract.py actually removes
recto-verso bleed-through while preserving the recto's own ink, using a
synthetic recto+verso pair with known ground-truth front strokes and known
bleed strokes.

The fixture deliberately includes one front stroke that traces almost
exactly over where a verso stroke's bleed-through lands (after the
flip+shift the module has to discover on its own) - that's what lets the
"strength too high" case actually have real front ink to erode into, rather
than only ever nibbling at background noise.

Run: pytest -q
"""
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"

sys.path.insert(0, str(SRC))
import bleed_subtract as bs  # noqa: E402

# --- synthetic fixture geometry ---------------------------------------------
W, H = 320, 240
BG_COLOR = (222, 214, 196)

# What's genuinely written on the FRONT of the leaf.
FRONT_STROKES = [
    ([(40, 40), (90, 35), (140, 55), (190, 40)], 230, 3),
    ([(40, 90), (100, 100), (160, 85), (220, 95)], 210, 3),
    ([(40, 140), (80, 155), (130, 135), (180, 150), (230, 140)], 200, 3),
    # Deliberately traces almost exactly over where VERSO_STROKES[0] lands
    # after mirror+shift (see make_synthetic_pair) - i.e. front ink and
    # bleed-through ink genuinely overlap here, the way they can on a real
    # leaf. This is what gives the "strength too high" test real front ink
    # to erode into, instead of only nibbling at background noise.
    ([(293, 57), (243, 47), (193, 67), (143, 52), (93, 62)], 220, 3),
]

# What's genuinely written on the BACK of the leaf (own strong ink, scanned directly).
VERSO_STROKES = [
    ([(30, 60), (80, 50), (130, 70), (180, 55), (230, 65)], 235, 3),
    ([(30, 120), (90, 130), (150, 110), (210, 125)], 220, 3),
    ([(30, 180), (70, 195), (120, 175), (170, 190), (220, 175), (260, 185)], 215, 3),
]

TRUE_DY, TRUE_DX = -3, 4          # injected front/back scan misregistration, within +/-20px
BLEED_ATTENUATION = 0.18          # fraction of verso ink strength that shows through as bleed

# --- calibrated thresholds, with rationale ----------------------------------
#
# Measured directly against this fixture (see calibration in the PR/commit
# that added this test): strength=1.0 (the CLI default) gets front_recall
# 1.000 and pure-bleed reduction 0.978; strength=0.05 gets reduction 0.034
# (bleed clearly still there); strength=10.0 gets front_recall 0.719 (the
# overlapping front stroke gets eaten). The thresholds below sit with large
# margins on the correct side of each of those measurements, so the tests
# are robust to minor incidental changes rather than pinned to exact floats.
GOOD_STRENGTH = 1.0
TOO_LOW_STRENGTH = 0.05
TOO_HIGH_STRENGTH = 10.0

FRONT_RECALL_MIN = 0.90            # spec: "preserving front strokes above 90% recall"
FRONT_RECALL_MAX_WHEN_TOO_HIGH = 0.90
BLEED_REDUCTION_MIN_SUCCESS = 0.6
BLEED_REDUCTION_MAX_TOO_LOW = 0.3

STROKE_DETECT_THRESHOLD = 40.0     # ink units; well above paper noise, well below real stroke ink


def _blank_paper(rng):
    arr = np.full((H, W, 3), BG_COLOR, dtype=np.float64)
    arr += rng.normal(0, 2.5, size=(H, W, 1))
    return arr


def _draw_strokes(strokes):
    """Render strokes onto a transparent RGBA layer, so we can both
    composite it (for the image) and read its alpha channel back out (for a
    pixel-exact ground-truth mask)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    for pts, darkness, width in strokes:
        draw.line(pts, fill=(40, 35, 30, darkness), width=width, joint="curve")
    return img


def make_synthetic_pair(seed=7, bleed_attenuation=BLEED_ATTENUATION, true_dy=TRUE_DY, true_dx=TRUE_DX):
    """Build a deterministic (seeded) recto/verso pair:
      - verso_bgr: a normal, strongly-inked scan of the back of the leaf.
      - recto_bgr: paper + a faint, MIRRORED, ATTENUATED, and (dy,dx)-SHIFTED
        copy of the verso's ink (simulating bleed-through with realistic
        scan misregistration) + the recto's own bold strokes on top.
    Returns (recto_bgr, verso_bgr, front_mask, bleed_mask) where the masks
    are pixel-exact ground truth for "real front ink" and "where bleed-
    through actually landed", independent of anything bleed_subtract.py
    itself computes.
    """
    rng = np.random.default_rng(seed)

    # --- verso: plain strongly-inked scan of the back ---
    verso_bg = _blank_paper(rng)
    verso_ink_layer = _draw_strokes(VERSO_STROKES)
    verso_img = Image.fromarray(np.clip(verso_bg, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    verso_img.alpha_composite(verso_ink_layer)
    verso_bgr = cv2.cvtColor(np.array(verso_img.convert("RGB")), cv2.COLOR_RGB2BGR)
    verso_ink_alpha = np.array(verso_ink_layer)[:, :, 3].astype(np.float64)

    # --- recto: paper + faint mirrored/shifted bleed + own bold strokes ---
    recto_bg = _blank_paper(rng)

    bleed_alpha = np.fliplr(verso_ink_alpha) * bleed_attenuation
    bleed_alpha_shifted = np.zeros_like(bleed_alpha)
    h, w = bleed_alpha.shape
    ay0, ay1 = max(0, true_dy), min(h, h + true_dy)
    ax0, ax1 = max(0, true_dx), min(w, w + true_dx)
    by0, by1 = max(0, -true_dy), min(h, h - true_dy)
    bx0, bx1 = max(0, -true_dx), min(w, w - true_dx)
    bleed_alpha_shifted[ay0:ay1, ax0:ax1] = bleed_alpha[by0:by1, bx0:bx1]

    ink_color = np.array([30, 35, 40], dtype=np.float64)
    frac = (bleed_alpha_shifted / 255.0)[:, :, None]
    recto_bg = recto_bg * (1 - frac) + ink_color * frac

    recto_front_layer = _draw_strokes(FRONT_STROKES)
    recto_img = Image.fromarray(np.clip(recto_bg, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    recto_img.alpha_composite(recto_front_layer)
    recto_bgr = cv2.cvtColor(np.array(recto_img.convert("RGB")), cv2.COLOR_RGB2BGR)

    front_alpha = np.array(recto_front_layer)[:, :, 3].astype(np.float64)
    front_mask = front_alpha > 40
    bleed_mask = bleed_alpha_shifted > 15

    return recto_bgr, verso_bgr, front_mask, bleed_mask


def _result_ink(result_image):
    """Grayscale 'ink' view of a bleed_subtract result image, for the
    recall/reduction metrics below (which only care about darkness, not
    hue). The result is left in the ORIGINAL scan's own illumination space
    (not pre-flat-fielded - see the double-flatfielding fix), so measuring
    its ink content means flat-fielding it exactly once via bs._to_ink(),
    the same way a real downstream consumer (enhance.py, verify_glyph.py)
    would."""
    return bs._to_ink(result_image, bs.DEFAULT_SIGMA)


def _front_recall(result_image, front_mask):
    ink_out = _result_ink(result_image)
    return float((ink_out[front_mask] > STROKE_DETECT_THRESHOLD).mean())


def _pure_bleed_reduction(recto_bgr, result_image, front_mask, bleed_mask):
    """Fraction of bleed-through ink magnitude removed, measured only on
    'pure' bleed pixels (bleed_mask minus any front-ink overlap) so the one
    deliberately-overlapping stroke doesn't distort this metric."""
    pure_bleed_mask = bleed_mask & ~front_mask
    before = bs._to_ink(recto_bgr, bs.DEFAULT_SIGMA)
    after = _result_ink(result_image)
    before_mean = before[pure_bleed_mask].mean()
    after_mean = after[pure_bleed_mask].mean()
    return float(1 - (after_mean / before_mean))


@pytest.fixture(scope="module")
def synthetic_pair():
    return make_synthetic_pair()


# --- alignment search -----------------------------------------------------

def test_finds_the_injected_alignment_offset(synthetic_pair):
    recto_bgr, verso_bgr, _, _ = synthetic_pair
    result = bs.remove_bleed_through(recto_bgr, verso_bgr, strength=GOOD_STRENGTH)
    assert result.dy == TRUE_DY
    assert result.dx == TRUE_DX


# --- the main behavior: remove bleed, keep front ink ------------------------

def test_default_strength_removes_bleed_and_preserves_front(synthetic_pair):
    recto_bgr, verso_bgr, front_mask, bleed_mask = synthetic_pair
    result = bs.remove_bleed_through(recto_bgr, verso_bgr, strength=GOOD_STRENGTH)

    recall = _front_recall(result.image, front_mask)
    reduction = _pure_bleed_reduction(recto_bgr, result.image, front_mask, bleed_mask)

    assert recall > FRONT_RECALL_MIN, f"front recall {recall:.3f} should be > {FRONT_RECALL_MIN}"
    assert reduction > BLEED_REDUCTION_MIN_SUCCESS, (
        f"bleed reduction {reduction:.3f} should be > {BLEED_REDUCTION_MIN_SUCCESS}"
    )


def test_zero_strength_is_an_exact_noop(synthetic_pair):
    """Regression test for the double-flatfielding fix: an earlier version
    wrote the output in flat-fielded space, so even --strength 0 (literally
    zero subtraction) came out different from the raw recto once a
    downstream tool flat-fielded it again - a ~9-unit artifact on real page
    data that had nothing to do with bleed removal. The output must now be
    left in the recto's own illumination space, so strength=0 means the
    correction is exactly zero everywhere and the result is byte-identical
    to the raw recto."""
    recto_bgr, verso_bgr, _, _ = synthetic_pair
    result = bs.remove_bleed_through(recto_bgr, verso_bgr, strength=0.0)
    assert np.array_equal(result.image, recto_bgr), (
        "strength=0 must be an exact no-op - any difference means the output "
        "isn't in the recto's own illumination space any more"
    )


def test_output_is_colour_8bit_and_reproducible(synthetic_pair):
    recto_bgr, verso_bgr, _, _ = synthetic_pair
    r1 = bs.remove_bleed_through(recto_bgr, verso_bgr, strength=GOOD_STRENGTH)
    r2 = bs.remove_bleed_through(recto_bgr, verso_bgr, strength=GOOD_STRENGTH)
    assert r1.image.dtype == np.uint8
    assert r1.image.ndim == 3
    assert r1.image.shape[2] == 3
    assert np.array_equal(r1.image, r2.image), "same input/params must give byte-identical output"


def test_output_is_colour_and_retains_recto_hue_where_no_bleed(synthetic_pair):
    """The bug this test guards against: bleed_subtract used to collapse
    both scans to grayscale internally, so its output was single-channel -
    which silently defeated enhance.py's blue-vs-bstar colour channel pick
    downstream (bstar scored exactly 0.0 on a grayscale-only input)."""
    recto_bgr, verso_bgr, front_mask, bleed_mask = synthetic_pair
    result = bs.remove_bleed_through(recto_bgr, verso_bgr, strength=GOOD_STRENGTH)

    # Structurally colour, not grayscale.
    assert result.image.ndim == 3
    assert result.image.shape[2] == 3

    # Genuinely carries colour - not 3 channels that just happen to be
    # identical (R=G=B), which would still "look" grayscale. Checked at
    # actual ink pixels, not blank paper: flatfield() correctly normalizes
    # uniform paper toward ~255 in every channel regardless of its original
    # hue (that's illumination correction working as intended, not a colour
    # bug), so blank paper alone wouldn't distinguish real colour from a
    # flattened R=G=B regression.
    pure_front = front_mask & ~bleed_mask
    b = result.image[..., 0].astype(int)
    r = result.image[..., 2].astype(int)
    assert np.abs(b - r)[pure_front].mean() > 1.0, "output looks like flattened grayscale, not real colour"

    # Where there is no bleed-through at all, only the recto's own colour
    # should be present - i.e. the result should closely track the RAW
    # recto (the output is deliberately left in the original's own
    # illumination space, not flat-fielded - see the double-flatfielding
    # fix), since only the ALIGNED VERSO INK is ever subtracted.
    safe_mask = ~bleed_mask
    diff = np.abs(result.image[safe_mask].astype(int) - recto_bgr[safe_mask].astype(int))
    assert diff.mean() < 2.0, "recto colour should be ~unchanged where there is no bleed to remove"


# --- failure modes: prove the metrics actually mean something ---------------

def test_strength_too_low_leaves_bleed_in_place(synthetic_pair):
    recto_bgr, verso_bgr, front_mask, bleed_mask = synthetic_pair
    result = bs.remove_bleed_through(recto_bgr, verso_bgr, strength=TOO_LOW_STRENGTH)

    reduction = _pure_bleed_reduction(recto_bgr, result.image, front_mask, bleed_mask)
    recall = _front_recall(result.image, front_mask)

    assert reduction < BLEED_REDUCTION_MAX_TOO_LOW, (
        f"strength={TOO_LOW_STRENGTH} should barely touch the bleed "
        f"(got reduction {reduction:.3f}, expected < {BLEED_REDUCTION_MAX_TOO_LOW})"
    )
    # sanity: being too gentle should never cost front recall
    assert recall > FRONT_RECALL_MIN


def test_strength_too_high_erases_overlapping_front_ink(synthetic_pair):
    recto_bgr, verso_bgr, front_mask, bleed_mask = synthetic_pair
    result = bs.remove_bleed_through(recto_bgr, verso_bgr, strength=TOO_HIGH_STRENGTH)

    recall = _front_recall(result.image, front_mask)
    reduction = _pure_bleed_reduction(recto_bgr, result.image, front_mask, bleed_mask)

    assert recall < FRONT_RECALL_MAX_WHEN_TOO_HIGH, (
        f"strength={TOO_HIGH_STRENGTH} should over-erode the overlapping front "
        f"stroke (got recall {recall:.3f}, expected < {FRONT_RECALL_MAX_WHEN_TOO_HIGH})"
    )
    # it does still remove the bleed - it's just not "gentle" any more
    assert reduction > BLEED_REDUCTION_MIN_SUCCESS


def test_mismatched_dimensions_raise_cleanly():
    recto_bgr = np.full((100, 100, 3), 220, dtype=np.uint8)
    verso_bgr = np.full((90, 100, 3), 220, dtype=np.uint8)
    with pytest.raises(ValueError, match="matching pixel dimensions"):
        bs.remove_bleed_through(recto_bgr, verso_bgr)


# --- end-to-end CLI: ingestion gate + file output ---------------------------

def _write_pair(tmp_path, recto_bgr, verso_bgr):
    recto_path = tmp_path / "recto.png"
    verso_path = tmp_path / "verso.png"
    cv2.imwrite(str(recto_path), recto_bgr)
    cv2.imwrite(str(verso_path), verso_bgr)
    return recto_path, verso_path


def test_cli_writes_bleedremoved_file_and_never_touches_safe_best(tmp_path, synthetic_pair):
    recto_bgr, verso_bgr, _, _ = synthetic_pair
    recto_path, verso_path = _write_pair(tmp_path, recto_bgr, verso_bgr)
    outdir = tmp_path / "bleed_out"

    result = subprocess.run(
        [sys.executable, str(SRC / "bleed_subtract.py"),
         "--recto", str(recto_path), "--verso", str(verso_path),
         "--outdir", str(outdir)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    out_files = list(outdir.glob("*_bleedremoved.png"))
    assert len(out_files) == 1
    assert not list(outdir.glob("*_safe_*")), "must never write anything named like a safe-BEST file"

    written = cv2.imread(str(out_files[0]), cv2.IMREAD_UNCHANGED)
    assert written.dtype == np.uint8
    assert written.ndim == 3
    assert written.shape[2] == 3


def test_cli_refuses_bad_recto_file(tmp_path, synthetic_pair):
    _, verso_bgr, _, _ = synthetic_pair
    verso_path = tmp_path / "verso.png"
    cv2.imwrite(str(verso_path), verso_bgr)

    impostor_recto = tmp_path / "recto.png"
    impostor_recto.write_bytes(b"this is plain text wearing a .png extension\n" * 3)

    outdir = tmp_path / "bleed_out"
    result = subprocess.run(
        [sys.executable, str(SRC / "bleed_subtract.py"),
         "--recto", str(impostor_recto), "--verso", str(verso_path),
         "--outdir", str(outdir)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )

    assert result.returncode != 0
    assert "REJECTED" in result.stderr
    assert "Traceback" not in result.stderr
    assert not outdir.exists() or not any(outdir.iterdir())
