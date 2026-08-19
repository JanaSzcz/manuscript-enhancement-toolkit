#!/usr/bin/env python3
"""
bleed_subtract.py - OPT-IN recto/verso bleed-through removal for the HTR
input path.

Some manuscript pages show ink from the OTHER side of the leaf showing
through the paper (bleed-through / show-through). Standard `enhance.py`
contrast enhancement has no way to tell that faint darkening apart from the
page's own faint ink, and can make it worse. This module is a separate,
opt-in tool for exactly that situation: given a scan of BOTH sides of the
same leaf, it estimates how much of the recto's faint darkening is explained
by the (mirrored) verso ink, and subtracts a gentle, proportional amount of
it - controlled by --strength - while leaving strong, bold recto strokes
alone.

This is NOT wired into pdf_to_png.py / enhance.py / verify_glyph.py and does
not change enhance.py or its math; it only imports enhance.flatfield() (used
unmodified, purely to normalize away uneven lighting before comparing the
two sides) exactly as the test suite already does. Nothing calls this module
automatically - run it by hand when a specific page needs it.

Usage:
  python bleed_subtract.py --recto RECTO.png --verso VERSO.png \
      [--strength 1.0] [--sigma 40] [--search-window 20] [--outdir bleed_removed]

Output: <recto-basename>_bleedremoved.png - a 3-channel 8-bit BGR colour PNG
(lighting-corrected, bleed-corrected; NOT contrast-stretched). Keeping this
in colour matters: enhance.py picks between a blue-channel and an L*a*b* b*
candidate downstream, and that pick is meaningless on a grayscale-only
input. Feed this file to src/enhance.py next for the full safe-enhance pass
if you want that too. Never overwrites, and is never named the same as, a
`*_safe_*_BEST.png` file.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import cv2
import numpy as np

from enhance import flatfield  # reused unmodified - see CLAUDE.md enhancement-math change policy
from ingest import validate_file, IngestRejected, resolve_output_path

# --- tunable constants -------------------------------------------------------
DEFAULT_SIGMA = 40            # matches enhance.py's --sigma default
DEFAULT_SEARCH_WINDOW = 20    # +/-20px alignment search, per spec
NOISE_FLOOR = 8.0             # ink units below which a pixel isn't trusted as "verso ink present"
MIN_CALIBRATION_PIXELS = 200  # minimum verso-ink-present pixels needed to estimate a bleed ratio


@dataclass
class BleedRemovalResult:
    image: np.ndarray    # uint8 BGR colour, HxWx3 - bleed-through subtracted
    dy: int               # best-found vertical offset of the (flipped) verso relative to the recto
    dx: int               # best-found horizontal offset
    correlation: float    # correlation score at the chosen offset (higher = more confident alignment)
    k: float               # estimated bleed-through attenuation ratio actually used


def _flatfield_bgr(bgr: np.ndarray, sigma: float) -> np.ndarray:
    """Lighting-corrected BGR (float64), reusing enhance.py's flatfield()
    unmodified purely to remove uneven illumination before comparing recto
    and verso - this is NOT part of, and does not alter, the enhancement
    pipeline itself. Kept in colour so the final subtraction can be applied
    per-channel, preserving the recto's own colour information."""
    return flatfield(bgr, sigma).astype(np.float64)


def _ink_from_flat_bgr(flat_bgr: np.ndarray) -> np.ndarray:
    """Grayscale 'ink' map from an already flat-fielded BGR array: ~0 =
    paper, positive = darker than paper. Used only for the alignment search
    and the k estimate, both of which stay single-channel by design - the
    colour information is preserved separately and only re-enters when the
    estimated bleed is subtracted, per-channel, from the flat-fielded BGR."""
    gray = cv2.cvtColor(np.clip(flat_bgr, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY)
    return 255.0 - gray.astype(np.float64)


def _to_ink(bgr: np.ndarray, sigma: float) -> np.ndarray:
    """Convenience wrapper: lighting-corrected grayscale ink map straight
    from a raw BGR image. Used for the alignment search / k estimate above,
    and by the test suite to measure ink content of an image."""
    return _ink_from_flat_bgr(_flatfield_bgr(bgr, sigma))


def _overlap_slices(shape, dy: int, dx: int):
    """Slice pairs describing the overlapping region of an array `a` and an
    array `b` shifted by (dy, dx) relative to `a` (b's content moves right
    by dx, down by dy)."""
    h, w = shape
    ay0, ay1 = max(0, dy), min(h, h + dy)
    ax0, ax1 = max(0, dx), min(w, w + dx)
    by0, by1 = max(0, -dy), min(h, h - dy)
    bx0, bx1 = max(0, -dx), min(w, w - dx)
    return (slice(ay0, ay1), slice(ax0, ax1)), (slice(by0, by1), slice(bx0, bx1))


def _crop_overlap(a: np.ndarray, b: np.ndarray, dy: int, dx: int):
    a_sl, b_sl = _overlap_slices(a.shape, dy, dx)
    return a[a_sl], b[b_sl]


def _place_shifted(ink: np.ndarray, dy: int, dx: int, shape) -> np.ndarray:
    """Place `ink` shifted by (dy, dx) onto a zero canvas of `shape`. Pixels
    with no corresponding verso data (outside the overlap after the shift)
    are treated as zero ink - never guessed at."""
    out = np.zeros(shape, dtype=np.float64)
    a_sl, b_sl = _overlap_slices(shape, dy, dx)
    out[a_sl] = ink[b_sl]
    return out


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    a = a.ravel().astype(np.float64)
    b = b.ravel().astype(np.float64)
    if a.size == 0:
        return 0.0
    a = a - a.mean()
    b = b - b.mean()
    denom = np.sqrt((a @ a) * (b @ b))
    if denom < 1e-9:
        return 0.0
    return float((a @ b) / denom)


def _find_best_offset(recto_ink: np.ndarray, verso_ink_flipped: np.ndarray, window: int):
    """Brute-force search over every integer (dy, dx) in [-window, window]
    for the shift where the flipped verso's ink correlates best with the
    recto's ink - i.e. the alignment most consistent with bleed-through."""
    best_dy, best_dx, best_score = 0, 0, -2.0
    for dy in range(-window, window + 1):
        for dx in range(-window, window + 1):
            a_crop, b_crop = _crop_overlap(recto_ink, verso_ink_flipped, dy, dx)
            if a_crop.size < 100:
                continue
            score = _correlation(a_crop, b_crop)
            if score > best_score:
                best_dy, best_dx, best_score = dy, dx, score
    return best_dy, best_dx, best_score


def remove_bleed_through(
    recto_bgr: np.ndarray,
    verso_bgr: np.ndarray,
    strength: float = 1.0,
    sigma: float = DEFAULT_SIGMA,
    search_window: int = DEFAULT_SEARCH_WINDOW,
) -> BleedRemovalResult:
    """Pure image-math core: two BGR arrays in, one BleedRemovalResult out.
    No file I/O, no ingestion gate - that's main()'s job, same split as
    enhance.py's flatfield()/levels() vs its main().
    """
    if recto_bgr.shape[:2] != verso_bgr.shape[:2]:
        raise ValueError(
            f"recto and verso must have matching pixel dimensions "
            f"(got {recto_bgr.shape[:2]} vs {verso_bgr.shape[:2]}) - "
            f"rescan or resize consistently before running this tool"
        )

    # Alignment search and k-estimation stay single-channel (grayscale ink
    # maps) - unchanged logic, just now derived from a colour-preserving
    # flat-fielded base rather than immediately collapsing to grayscale.
    recto_flat = _flatfield_bgr(recto_bgr, sigma)
    verso_flat = _flatfield_bgr(verso_bgr, sigma)
    recto_ink = _ink_from_flat_bgr(recto_flat)
    verso_ink = _ink_from_flat_bgr(verso_flat)
    # Mirror: seen through the paper from the front, the verso's writing is
    # flipped left-right (top-bottom stays the same when a page is turned
    # like a book leaf).
    verso_ink_flipped = np.fliplr(verso_ink)

    dy, dx, correlation = _find_best_offset(recto_ink, verso_ink_flipped, search_window)
    aligned_verso_ink = _place_shifted(verso_ink_flipped, dy, dx, recto_ink.shape)

    # Estimate the bleed-through attenuation ratio: at locations where the
    # aligned verso clearly has ink, how dark does that typically make the
    # recto? A robust (median) ratio, not a mean, so a handful of pixels
    # where recto's own bold ink happens to coincide doesn't skew it.
    mask = aligned_verso_ink > NOISE_FLOOR
    if mask.sum() >= MIN_CALIBRATION_PIXELS:
        ratios = recto_ink[mask] / aligned_verso_ink[mask]
        k = float(np.median(np.clip(ratios, 0.0, 1.0)))
    else:
        k = 0.0  # not enough signal to trust an estimate - do nothing rather than guess

    # Subtraction is now per-channel: the SAME estimated bleed amount
    # (still one grayscale map - the bleed estimate itself is not colour-
    # aware) is removed equally from B, G, and R, rather than collapsing
    # the recto to one channel first. Wherever there's no aligned verso ink,
    # predicted_bleed is ~0 and the recto's own colour passes through
    # unchanged; only the bleed-explained darkening is subtracted.
    predicted_bleed = strength * k * aligned_verso_ink
    result_bgr = np.clip(recto_flat + predicted_bleed[:, :, None], 0.0, 255.0).astype(np.uint8)

    return BleedRemovalResult(image=result_bgr, dy=dy, dx=dx, correlation=correlation, k=k)


def main():
    ap = argparse.ArgumentParser(
        description="OPT-IN recto/verso bleed-through removal. Not part of "
                     "the automatic pipeline - run by hand when a page shows "
                     "visible show-through from the other side."
    )
    ap.add_argument("--recto", required=True, help="path to the recto (front) page scan")
    ap.add_argument("--verso", required=True, help="path to the verso (back) page scan")
    ap.add_argument("--strength", type=float, default=1.0,
                     help="multiplier on the auto-estimated bleed-through ratio (default 1.0)")
    ap.add_argument("--sigma", type=float, default=DEFAULT_SIGMA)
    ap.add_argument("--search-window", type=int, default=DEFAULT_SEARCH_WINDOW)
    ap.add_argument("--outdir", default="bleed_removed")
    a = ap.parse_args()

    try:
        recto_validated = validate_file(a.recto)
        verso_validated = validate_file(a.verso)
    except IngestRejected as e:
        print(f"REJECTED: {e}", file=sys.stderr)
        sys.exit(1)

    recto_bgr = cv2.imread(str(recto_validated.path))
    verso_bgr = cv2.imread(str(verso_validated.path))

    try:
        result = remove_bleed_through(
            recto_bgr, verso_bgr,
            strength=a.strength, sigma=a.sigma, search_window=a.search_window,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    out_path = resolve_output_path(recto_validated, "_bleedremoved.png", outdir=a.outdir)
    cv2.imwrite(str(out_path), result.image)

    print(f"best alignment: dy={result.dy} dx={result.dx}  correlation={result.correlation:.3f}")
    print(f"estimated bleed-through ratio k={result.k:.3f}  strength={a.strength}")
    print(f"wrote {out_path}")
    print("This output is bleed-corrected only, NOT contrast-enhanced. Run "
          "src/enhance.py on it next for the full safe-enhance pass, and "
          "always confirm any reading against the untouched original.")


if __name__ == "__main__":
    main()
