"""
tests/test_invariants.py — locks the safety contract described in CLAUDE.md.

These tests drive the REAL pipeline exactly as a user would: they shell out to
`python src/enhance.py ...` and inspect the files it writes. They do not
reimplement or alter the enhancement math — `flatfield()` is imported from
`src/enhance.py` in a couple of tests, but only to compute a lighting-corrected
reference for scoring test results, never to change what the pipeline does.

Run: pytest -q
A green suite here is the precondition for any enhancement-math change
(see "Enhancement-math change policy" in CLAUDE.md).
"""
import glob
import hashlib
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "samples" / "sample_page.png"
ENHANCE_SCRIPT = REPO_ROOT / "src" / "enhance.py"

sys.path.insert(0, str(REPO_ROOT / "src"))
from enhance import flatfield  # noqa: E402  (reused only to score results, not to change behaviour)

# --- threshold constants, with rationale -----------------------------------
#
# NOT_BINARIZED_MIN_UNIQUE / MIDTONE_FRAC_MIN
#   Straight from the spec in CLAUDE.md: a binarized (2-level) image has at
#   most 2 unique values and essentially all pixels pinned at 0 or 255. A
#   healthy grayscale-enhanced page has dozens of levels and a real spread of
#   mid-tones (paper grain, stroke edges, antialiasing). >32 unique values and
#   >5% of pixels strictly inside [17, 238] cleanly separates the two cases
#   while staying easy to clear for any non-degenerate photograph.
NOT_BINARIZED_MIN_UNIQUE = 32
MIDTONE_FRAC_MIN = 0.05

# ORIG_INK_ABS_THRESH / FAB_DELTA_THRESH / FAB_DILATE_PX / FAB_OPEN_PX / FAB_FRAC_LIMIT
#   Used by test_no_fabrication. `flatfield()` (the pipeline's own first
#   step) divides the image by a heavily-blurred copy of itself, so blank
#   paper collapses tightly to ~255 regardless of uneven lighting, while any
#   real ink (even very faint ink) reads meaningfully below that. Calibrated
#   against a synthetic image where the true ink pixels are known: a
#   flat-fielded value < 240 recovers 99.5% of real ink while misclassifying
#   only ~0.2% of blank paper — a deliberately lenient "maybe ink" mask, so
#   that legitimately very faint strokes don't get flagged as "blank paper"
#   later. It is dilated by a 9px ellipse to allow a few pixels of slack for
#   where CLAHE/contrast changes shift a stroke edge.
#
#   "Added ink" = pixels where the enhanced output got at least 15% (of the
#   image's 1st-99th percentile dynamic range) darker than that flat-fielded
#   original. A 3px morphological opening removes single-pixel noise that
#   CLAHE's local contrast stretching inevitably amplifies on blank paper
#   (verified: without opening, this noise alone produces a large false
#   "added ink" signal that has nothing to do with fabrication).
#
#   The failure metric is (added-ink pixels that fall outside the dilated
#   "maybe ink" mask) / (total pixels), not a fraction of the added-ink
#   pixels — the denominator otherwise collapses to a handful of pixels and
#   becomes noisy. On this sample the real pipeline measures ~0.018% of
#   total pixels; a deliberately injected fabricated blob as small as 15x15
#   pixels (much smaller than a single manuscript letter) measures ~0.10%.
#   0.08% sits with ~4x margin above the real pipeline's noise floor while
#   still catching that injected blob — verified directly during calibration
#   by patching in fake ink and re-running this exact check.
ORIG_INK_ABS_THRESH = 240
FAB_DELTA_THRESH = 0.15
FAB_DILATE_PX = 9
FAB_OPEN_PX = 3
FAB_FRAC_LIMIT = 0.0008

# INK_PRESERVED_RECALL_MIN
#   Used by test_ink_preserved. "Ink still visible" in the enhanced output is
#   defined as the darkest 10% of its own pixels (a non-trivial, fairly
#   tight definition — not "half the image"). Recall = fraction of the
#   original's flat-fielded ink mask that's still covered by that enhanced
#   ink mask. The real pipeline measures ~99.5% recall on this sample;
#   simulated stroke-deletion bugs (painting real strokes over with paper
#   white) drop recall to 69-88%. 90% cleanly separates a healthy pipeline
#   from one that's erasing real ink, with room for minor edge/antialiasing
#   shift.
INK_PRESERVED_RECALL_MIN = 0.90

# Sigma used only to build the lighting-corrected reference mask below. Must
# match the --sigma default in src/enhance.py's CLI (currently 40) since
# enhanced_dir() below runs the CLI with no --sigma override.
FLATFIELD_SIGMA = 40


# --- helpers -----------------------------------------------------------------

def run_enhance(outdir, image=SAMPLE, extra_args=None):
    cmd = [sys.executable, str(ENHANCE_SCRIPT), str(image), "--outdir", str(outdir)]
    if extra_args:
        cmd += extra_args
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, (
        f"src/enhance.py failed (exit {result.returncode}):\n{result.stderr}"
    )


def find_best(outdir):
    matches = glob.glob(str(Path(outdir) / "*_BEST.png"))
    assert matches, f"no *_BEST.png written to {outdir}"
    return Path(matches[0])


def percentile_normalize(gray):
    lo, hi = np.percentile(gray, 1), np.percentile(gray, 99)
    return np.clip((gray.astype(float) - lo) / (hi - lo), 0, 1)


# --- fixtures ------------------------------------------------------------

@pytest.fixture(scope="module")
def enhanced_dir(tmp_path_factory):
    assert SAMPLE.exists(), f"missing sample image: {SAMPLE}"
    outdir = tmp_path_factory.mktemp("enhance_out")
    run_enhance(outdir)
    return outdir


@pytest.fixture(scope="module")
def enhanced_best(enhanced_dir):
    path = find_best(enhanced_dir)
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    assert img is not None, f"could not read {path}"
    return img, path


@pytest.fixture(scope="module")
def orig_flat_gray():
    bgr = cv2.imread(str(SAMPLE))
    flat = flatfield(bgr, FLATFIELD_SIGMA)
    return cv2.cvtColor(flat.astype(np.uint8), cv2.COLOR_BGR2GRAY)


# --- 1. not binarized ------------------------------------------------------

def test_not_binarized(enhanced_best):
    img, path = enhanced_best
    n_unique = len(np.unique(img))
    assert n_unique > NOT_BINARIZED_MIN_UNIQUE, (
        f"{path.name} has only {n_unique} distinct gray levels "
        f"(need > {NOT_BINARIZED_MIN_UNIQUE}); looks binarized/thresholded"
    )
    midtone_frac = np.mean((img > 16) & (img < 239))
    assert midtone_frac > MIDTONE_FRAC_MIN, (
        f"{path.name} has only {midtone_frac:.1%} mid-tone pixels "
        f"(need > {MIDTONE_FRAC_MIN:.0%}); looks binarized/thresholded"
    )


# --- 2. grayscale 8-bit -----------------------------------------------------

def test_grayscale_8bit(enhanced_best):
    img, path = enhanced_best
    assert img.dtype == np.uint8, f"{path.name} is {img.dtype}, expected uint8"
    assert img.ndim == 2, (
        f"{path.name} has shape {img.shape}, expected a single channel (H, W)"
    )


# --- 3. no fabrication -------------------------------------------------------

def test_no_fabrication(enhanced_best, orig_flat_gray):
    img, path = enhanced_best

    orig_n = percentile_normalize(orig_flat_gray)
    enh_n = percentile_normalize(img)
    delta = orig_n - enh_n  # positive => enhanced got darker than original

    added_raw = (delta > FAB_DELTA_THRESH).astype(np.uint8)
    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (FAB_OPEN_PX, FAB_OPEN_PX))
    added = cv2.morphologyEx(added_raw, cv2.MORPH_OPEN, open_kernel).astype(bool)

    orig_ink = orig_flat_gray < ORIG_INK_ABS_THRESH
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (FAB_DILATE_PX, FAB_DILATE_PX))
    orig_ink_dilated = cv2.dilate(orig_ink.astype(np.uint8), dilate_kernel).astype(bool)

    fabricated = added & ~orig_ink_dilated
    frac = fabricated.sum() / fabricated.size
    assert frac < FAB_FRAC_LIMIT, (
        f"{path.name}: {frac:.4%} of pixels look like ink added on blank paper "
        f"(limit {FAB_FRAC_LIMIT:.4%}) — possible fabrication"
    )


# --- 4. ink preserved ---------------------------------------------------------

def test_ink_preserved(enhanced_best, orig_flat_gray):
    img, path = enhanced_best

    orig_ink = orig_flat_gray < ORIG_INK_ABS_THRESH
    assert orig_ink.sum() > 0, "sample image has no ink pixels to test against"

    enh_ink = img < np.percentile(img, 10)
    recall = (orig_ink & enh_ink).sum() / orig_ink.sum()
    assert recall > INK_PRESERVED_RECALL_MIN, (
        f"{path.name}: only {recall:.1%} of original ink is still visible "
        f"after enhancement (need > {INK_PRESERVED_RECALL_MIN:.0%}) — "
        f"looks like real strokes were deleted"
    )


# --- 5. reproducible -----------------------------------------------------------

def test_reproducible(tmp_path):
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"
    run_enhance(out1)
    run_enhance(out2)

    files1 = sorted(Path(out1).glob("*.png"))
    files2 = sorted(Path(out2).glob("*.png"))
    names1 = [f.name for f in files1]
    names2 = [f.name for f in files2]
    assert names1 == names2 and names1, "the two runs produced different output files"

    for f1, f2 in zip(files1, files2):
        h1 = hashlib.sha256(f1.read_bytes()).hexdigest()
        h2 = hashlib.sha256(f2.read_bytes()).hexdigest()
        assert h1 == h2, f"{f1.name} differs between two runs on the same input"
