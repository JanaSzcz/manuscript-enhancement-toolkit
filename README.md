# Manuscript HTR Toolkit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A small toolkit for preparing faded handwritten manuscript scans (currently a
1507 Latin astrological manuscript, with Latin annotations) so they can be
transcribed by handwriting-recognition tools such as Claude, Transkribus, or
ChatGPT.

The toolkit's job is to make existing, faint ink **easier to see** — never to
invent or delete strokes. Its outputs feed a scholarly methodology article, so
correctness and provenance matter more than speed. See
[`CLAUDE.md`](CLAUDE.md) for the full contract this project follows.

## Setup

Use a virtual environment, not your system Python or conda:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Everything runs locally and offline — no cloud calls or accounts needed for
the image pipeline.

## The three scripts

Run these as plain scripts from the repo root, with the virtualenv active.
(They live in `src/`; the module examples below assume that layout.)

### 1. `src/pdf_to_png.py` — render a PDF page to PNG

Turns a scanned PDF page into a high-resolution, lossless colour PNG — the
format the HTR/LLM engines expect, and one that doesn't smear faint ink the
way JPEG does.

```bash
python src/pdf_to_png.py INPUT.pdf --dpi 400 --outdir outputs/pages
```

- `--dpi` — render resolution (default 400). The script prints each page's
  pixel size so you can sanity-check it — a full page should come out around
  3000–5000 px on the long side.
- `--outdir` — where to write the PNGs (default `pages`).
- `--pages` — optional page selection, e.g. `--pages 1-3,7`.

If a page comes out under ~2500 px on its long side, the script flags it as
too low-resolution to benefit from enhancement.

### 2. `src/enhance.py` — reveal faint ink safely

Runs the safe enhancement pipeline (flat-field correction → channel pick →
CLAHE contrast → levels) on a page PNG. It never binarizes and never fabricates
ink — it only makes existing faint strokes easier to see.

```bash
python src/enhance.py PAGE.png --sigma 40 --clip 2.5 --upscale 1.7 --outdir outputs/enhanced
```

This writes several files:

- `*_safe_blue.png` and `*_safe_bstar.png` — two enhanced candidates (one per
  colour channel). One of them is tagged `_BEST` — start there.
- `*_pointer_sharp.png` — a sharpened, upscaled version. This is a **pointer
  only**, meant to help you locate a hard-to-read spot. Never treat it as
  evidence for a transcription reading.

Always read from the `*_safe_*_BEST.png` file, and confirm any contested
reading against the untouched original.

### 3. `src/verify_glyph.py` — check one contested letter or word

Produces a single panel comparing the raw crop, the safe-enhanced crop, the
sharpened "pointer" crop, and a diff map, for one small region of a page. Use
this whenever a reading is in doubt.

```bash
python src/verify_glyph.py PAGE.png 0.55 0.10 0.35 0.16 --frac
```

- Give the crop box either in pixels (`x y w h`) or as fractions of the page
  (`0`–`1`) with `--frac`.
- `--zoom` controls how much the crop is enlarged (default 4).
- `--out` sets the output filename (default `glyph_check.png`).

In the diff panel, **green** means enhancement darkened or added ink, and
**red** means it removed ink. Only trust a reading if the shape is visible in
the RAW crop too, and if there's no green sitting on blank paper.

## A note on safety invariants

This toolkit is built around a small set of rules that are never relaxed,
because its output becomes evidence for a historical transcription:

- **Reveal, never fabricate.** Enhancement may only make faint, *existing*
  ink easier to see. It must never create ink on blank paper or delete real
  strokes.
- **Never binarize.** No pure black-and-white / threshold conversion — faint
  strokes die there, and HTR engines want grayscale anyway.
- **Grayscale PNG only.** Working files stay 8-bit single-channel PNG (or
  TIFF) — no JPEG, which smears faint ink.
- **The sharpened/upscaled image is a pointer, not evidence.** It's only for
  locating a spot, always written to its own `*_pointer_*` file, and must
  never be used as the basis for a reading.
- **Reproducibility.** The same input and parameters always produce
  byte-identical output — no randomness, no baked-in timestamps.

These are enforced by the test suite in `tests/test_invariants.py`. Full
details, including the ingestion-safety rules for untrusted input files, are
in [`CLAUDE.md`](CLAUDE.md).
