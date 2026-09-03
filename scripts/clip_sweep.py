#!/usr/bin/env python3
"""
clip_sweep.py - orchestration only. Runs the existing, unmodified
src/enhance.py once per --clip value on one already-rendered page PNG, so you
can eyeball how CLAHE's clipLimit affects the safe output.

This script does not implement, duplicate, or alter any enhancement math. It
shells out to enhance.py exactly as the CLI would, once per clip value with
every other parameter left at enhance.py's own defaults, and simply collects
the resulting "*_safe_*_BEST.png" from each run under a clip-tagged filename.
No CER/Transkribus scoring, no automatic "best clip" pick - this is a by-eye
comparison tool. Not part of the Stage 1-5 manuscript-page workflow ritual in
CLAUDE.md (it doesn't itself constitute converting/enhancing a page for a
reading - each run's output should go through Compare like any other
enhancement if it's going to be read).

Usage:
  python scripts/clip_sweep.py PAGE.png [--clip 2.5 3.5 5.0] [--outdir outputs/clip_sweep]
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SRC_DIR = SCRIPT_DIR.parent / "src"
ENHANCE_PY = SRC_DIR / "enhance.py"

sys.path.insert(0, str(SRC_DIR))
from ingest import validate_file, resolve_output_path, IngestRejected  # noqa: E402

DEFAULT_CLIPS = [2.5, 3.5, 5.0]


def fmt_clip(value: float) -> str:
    """Filename-friendly rendering of a clip value, always with a fixed
    decimal point so 5.0 reads as '5.0', not '5' (e.g. 2.5 -> '2.5',
    5.0 -> '5.0'). Extra precision beyond one decimal (e.g. 2.75) is kept
    rather than rounded away."""
    s = f"{value:g}"
    if "." not in s:
        s = f"{value:.1f}"
    return s


def run_one_clip(image_path: Path, clip: float, outdir: Path, validated) -> Path:
    """Run enhance.py at a single clip value in an isolated temp dir, then
    copy its *_safe_*_BEST.png into outdir under a clip-tagged name. Returns
    the final output path. Raises RuntimeError / FileNotFoundError on
    failure."""
    with tempfile.TemporaryDirectory(prefix="clip_sweep_") as tmpdir:
        cmd = [
            sys.executable, str(ENHANCE_PY), str(image_path),
            "--clip", str(clip),
            "--outdir", tmpdir,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"enhance.py failed for clip={clip}: {result.stderr.strip() or result.stdout.strip()}"
            )

        best_matches = list(Path(tmpdir).glob("*_safe_*_BEST.png"))
        if not best_matches:
            raise FileNotFoundError(
                f"no *_safe_*_BEST.png produced by enhance.py for clip={clip}"
            )
        best_file = best_matches[0]

        # Build the destination path through the shared ingestion helper -
        # never by hand-assembling a path from the raw input filename.
        dest = resolve_output_path(validated, f"_clip{fmt_clip(clip)}.png", outdir)
        shutil.copyfile(best_file, dest)
        return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", help="already-rendered page PNG (or PDF/JPEG/TIFF - anything the ingestion gate accepts)")
    ap.add_argument("--clip", type=float, nargs="+", default=DEFAULT_CLIPS,
                     help=f"CLAHE clip-limit values to sweep (default: {DEFAULT_CLIPS})")
    ap.add_argument("--outdir", default="outputs/clip_sweep",
                     help="directory to write the swept outputs to (default: outputs/clip_sweep)")
    args = ap.parse_args()

    try:
        validated = validate_file(args.image)
    except IngestRejected as e:
        print(f"REJECTED: {e}", file=sys.stderr)
        sys.exit(1)

    if not ENHANCE_PY.is_file():
        print(f"ERROR: expected enhance.py at {ENHANCE_PY}", file=sys.stderr)
        sys.exit(1)

    outdir = Path(args.outdir)
    results = []   # (clip, path_or_None, error_or_None)
    for clip in args.clip:
        try:
            dest = run_one_clip(Path(args.image), clip, outdir, validated)
            results.append((clip, dest, None))
        except (RuntimeError, FileNotFoundError) as e:
            results.append((clip, None, str(e)))

    print(f"\nclip sweep for {validated.safe_basename} (sha256 {validated.sha256[:12]}...):")
    any_failed = False
    for clip, dest, err in results:
        if dest is not None:
            print(f"  clip={fmt_clip(clip):>5}  -> {dest}")
        else:
            any_failed = True
            print(f"  clip={fmt_clip(clip):>5}  -> FAILED: {err}")

    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
