# Manuscript HTR Prep Toolkit

A three-stage pipeline for getting faded handwritten manuscripts ready for AI
transcription (Claude, Transkribus, ChatGPT), with a built-in safeguard against
fabricating readings.

**The one principle that governs everything below:** enhancement may only make
*visible* what is *already present*. It must never invent or delete strokes. The
untouched original is the sole court of final appeal — every reading has to be
confirmable there.

---

## Why PNG is the target format

You need one format that all three engines accept *and* that preserves faint ink:

| Format | Faint ink | Transkribus | Claude / ChatGPT upload | Verdict |
|--------|-----------|-------------|--------------------------|---------|
| TIFF   | excellent (lossless) | yes | **often rejected** by chat UIs | archival master only |
| PNG    | excellent (lossless) | yes | yes | **working format** |
| JPEG   | poor (smears thin strokes) | yes | yes | avoid for faded ink |
| Bitonal/B&W | destroys faint strokes | yes | yes | never |

So: keep the source PDF/TIFF as the archival master, and do all AI work on
**colour, lossless PNG**. Never binarize.

---

## Process 1 — PDF → high-res PNG

**Goal:** render each page to colour PNG at a resolution high enough for HTR
(300 DPI minimum, 400–600 the sweet spot for faded hands), and flag when the
source PDF is too low-res to benefit.

**Script:** `pdf_to_png.py`

```
pip install pypdfium2 pillow
python pdf_to_png.py INPUT.pdf --dpi 400 --outdir pages
# optional: --pages 1-3,7   to render a subset
```

**Checks after running:**
- A full manuscript page should be roughly **3000–5000 px on the long side**.
  The script prints each page's pixel size and warns if it looks low-res.
- If it warns, the PDF is only *wrapping* low-res images — re-rendering at a
  higher DPI won't add detail. Go back to the archive for a better master scan.
- Confirm output is RGB, not grayscale/bitonal.

---

## Process 2 — Enhancement (reveal, don't fabricate)

**Order of operations (this order matters):**

1. **Flat-field** — divide the image by a heavily blurred copy of itself. Removes
   paper tone and uneven lighting. *Safe by construction:* it changes what's
   behind the ink, not the ink. Blur sigma ~40; raise it until all text vanishes
   in the blurred copy.
2. **Channel selection** — the script computes both the **blue channel** (wins on
   cool/white paper) and **Lab b\*** (wins on yellow paper) and auto-picks the
   higher-contrast one, but writes **both** so you can judge per document.
   *Also safe:* picking a colour slice can't add a stroke that wasn't there.
3. **CLAHE** — local adaptive contrast (clip 2.5, 8×8 tiles). Evens out fading
   across the page. Keep the clip limit modest; high values amplify paper texture
   into stroke-like noise.
4. **Levels** — gentle 1/99 percentile clip. Keep it grayscale.
5. **Sharpen + upscale** *(optional, POINTER ONLY)* — unsharp mask + 1.7× upscale.
   This is the one step that *can* fabricate (halos splitting/merging strokes), so
   its output is written to a separate `*_pointer_sharp.png` and must never be
   your evidence — only a hint about where to look.

**Golden rules:** never binarize · output stays grayscale PNG · read from the
`*_safe_*_BEST.png` · **also run the untouched original through the engine** —
heavy processing sometimes pushes the image off the model's training distribution
and *lowers* accuracy, so keep whichever scores better.

**Script:** `enhance.py`

```
pip install opencv-python numpy
python enhance.py PAGE.png --outdir enhanced
# knobs: --sigma 40  --clip 2.5  --upscale 1.7
```

Outputs: `*_safe_blue_BEST.png` (or `bstar`), the other channel candidate, and
`*_pointer_sharp.png`.

---

## Process 3 — "Verify one glyph"

**Goal:** vet a single contested letter/word objectively, without the confirmation
bias that creeps in when you compare images by eye. Produces a 4-panel strip for
one crop:

- **RAW** — the untouched source (your ground truth)
- **SAFE** — flat-field + channel + CLAHE + levels
- **SHARP** — pointer version
- **DIFF** — green where processing *darkened/added* ink, red where it *removed*
  ink

**How to read the DIFF, the whole point of the tool:**
- Green sitting *on* existing strokes = trustworthy (revealed faint ink).
- Green sitting on *blank paper* between/around letters = **fabrication flag** —
  discard that reading.
- If a stroke you want to rely on is visible in SAFE/SHARP but you cannot find
  *any* trace of it in RAW at zoom, treat it as an artifact, not evidence.

**Script:** `verify_glyph.py`

```
python verify_glyph.py IMAGE.png X Y W H            # crop box in pixels
python verify_glyph.py IMAGE.png 0.55 0.10 0.35 0.16 --frac   # fractional 0–1
# options: --zoom 5  --out glyph_check.png
```

Use fractional coords (`--frac`) when you're eyeballing a location as "about 55%
across, 10% down"; use pixel coords when you have exact numbers.

---

## Quick start (all three)

```
pip install pypdfium2 pillow opencv-python numpy

# 1. PDF -> PNG pages
python pdf_to_png.py manuscript.pdf --dpi 400 --outdir pages

# 2. enhance one page
python enhance.py pages/manuscript_p021.png --outdir enhanced

# 3. vet a contested word on that page
python verify_glyph.py pages/manuscript_p021.png 0.55 0.10 0.35 0.16 --frac
```

Then feed BOTH `enhanced/*_safe_*_BEST.png` and the original page to your HTR/LLM
of choice, and confirm every uncertain reading against the original.

---

## Paste-ready prompts

These are for running each stage in a code-capable AI chat (Claude with code
execution, or ChatGPT with the code interpreter) by attaching your file and
pasting the prompt. Each is self-contained — it tells the model exactly what to do
even if it doesn't have these scripts.

### Prompt 1 — PDF → PNG

> I've attached a PDF of scanned manuscript pages with faded handwriting on
> yellowed paper. Render every page (or pages [LIST] if I named them) to
> **colour, lossless PNG at 400 DPI**. Do not binarize, do not convert to
> grayscale, do not use JPEG. For each page, report the output pixel dimensions
> and flag any page whose long side is under ~2500 px as too low-resolution to
> benefit from HTR. Give me the PNGs to download and tell me which pages, if any,
> I should re-source at higher resolution.

### Prompt 2 — Enhance for HTR/LLM reading

> I've attached a PNG of a single manuscript page with faint iron-gall ink on
> toned paper. Enhance it to make the handwriting more legible for HTR, using this
> exact order and nothing that fabricates strokes:
> 1. flat-field: divide the image by a Gaussian-blurred copy (sigma ~40, blurred
>    until all text vanishes) to remove paper tone and uneven lighting;
> 2. compute BOTH the blue channel and the inverted Lab b\* channel, tell me each
>    one's contrast (std dev), and pick the higher one — but show me both;
> 3. CLAHE (clip 2.5, 8×8 tiles);
> 4. gentle levels (1/99 percentile clip), staying 8-bit grayscale.
> Do NOT binarize. Save the result as grayscale PNG. Separately, give me a
> sharpened+1.7×-upscaled version labelled clearly as a "pointer only" that I
> should not use as evidence. Remind me to also run the untouched original through
> the engine and keep whichever transcribes better.

### Prompt 3 — Verify one glyph

> I've attached a manuscript page PNG. I want to vet one contested word without
> confirmation bias. The region is approximately [X% across, Y% down, W% wide,
> H% tall] (or exact pixel box [X Y W H]). Produce a single stacked image with
> four labelled, zoomed panels of that crop: (1) RAW untouched, (2) SAFE enhance
> = flat-field + auto channel pick + CLAHE + gentle levels, (3) SHARP pointer
> version, (4) a DIFF map that is green where processing darkened/added ink and
> red where it removed ink. Then tell me: does the DIFF show any green sitting on
> blank paper (a fabrication flag), and is the shape I'm reading traceable in the
> RAW panel? Only endorse a reading confirmable in RAW.

**Bonus — transcription prompt** (feed the enhanced PNG for the actual reading):

> This is a [16th-century Latin / German / …] manuscript hand. Transcribe it
> diplomatically: preserve original spelling and abbreviations, expand
> abbreviations in [square brackets], and mark any letters you cannot read with a
> confidence flag rather than guessing. For any word you're unsure of, list 2–3
> candidate readings with reasons. Do not normalize, modernize, or invent text to
> make it grammatical. Then give a clean expanded reading and a translation
> separately.
