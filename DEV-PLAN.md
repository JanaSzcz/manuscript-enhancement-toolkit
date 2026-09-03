# Development Plan & Session Handoff

Written so a fresh session (you, or Claude Code, or a new Claude chat) can pick up
without re-deriving context. Read the **State snapshot** first, then **Start here
next**, then the specific plan for whatever you're working on.

---

## State snapshot (where the project stands)

**What the toolkit is:** a tested, version-controlled Python toolkit that prepares
faded manuscript scans for AI transcription (Transkribus/LLMs), enhancing images to
reveal faint ink *without fabricating strokes*. Outputs feed a scholarly methodology
article, so correctness and provenance outrank speed.

**Repo contents:**
- `src/pdf_to_png.py` — PDF → colour PNG @ 400 DPI (render once).
- `src/enhance.py` — flat-field → channel-pick (blue vs Lab b*) → CLAHE → levels,
  plus a separate `*_pointer_sharp.png` (pointer, not evidence). Defaults: sigma 40,
  clip 2.5, upscale 1.7.
- `src/verify_glyph.py` — RAW | SAFE | SHARP | DIFF panel for one crop (green = ink
  added/darkened, red = removed).
- `src/ingest.py` — shared validation gate (type/size/dimension/PDF caps, path
  safety, SHA-256 provenance).
- `src/bleed_subtract.py` — recto–verso bleed-through removal; now **per-channel
  (colour-preserving)** after today-ish fix.
- `scripts/clip_sweep.py` — parameter sweep helper (created recently; runs enhance
  at several clip values on one raw page for eyeball comparison).
- `tests/` — invariant suite (5), ingest (18), CLI ingestion e2e (3), bleed-subtract
  (incl. colour-retention). **~35 passing** at last check.
- `CLAUDE.md` — invariants, ingestion protection, session workflow choreography.
- `.claude/commands/newpage.md` — `/newpage` workflow command.
- `docs/session-terminal.md`, `docs/session-claude-code.md` — per-tool session rituals.
- venv + pinned `requirements.txt`. `outputs/` is git-ignored (confirmed). Source
  scans/PDFs kept **entirely outside the repo**.

**Enhancement tuning status:**
- Clip sweep done by eye: **5.0 too much**; candidates **2.5 / 3.0 / 3.5**; 3.0–3.5
  look crisper but bring **more background noise**. No value committed as new default
  yet.
- Sigma sweep **planned but not run**: fix clip at 3.0, sweep sigma 40 / 60 / 80 to
  see if a larger flat-field blur calms the background noise. (Larger sigma =
  smoother background; too large = uneven lighting returns.)
- Sharpen/upscale lever: **leave alone** (fabrication risk) unless clip+sigma prove
  insufficient, and only then with the DIFF check.

---

## Open blockers & threads (priority order)

1. **[BLOCKER] Double flat-field bug.** `bleed_subtract.py` flat-fields internally;
   `enhance.py` / `verify_glyph.py` flat-field *again* when fed a `_bleedremoved.png`.
   Flat-field is non-idempotent → ~9-unit stroke-contrast shift, independent of
   `--strength` (proven by a strength=0 control still showing the shift). **Must fix
   before any CER measurement** — otherwise the general-vs-bleed comparison is
   confounded by how many times flat-field ran, not just by bleed removal.
   *Likely fix:* bleed module flat-fields internally only for k-estimation/alignment,
   but applies subtraction to the **original colour recto** and outputs an
   **un-flat-fielded** image; `enhance.py` then does the single flat-field on clean
   input. Needs a new test: "a `_bleedremoved.png` through `enhance.py` is
   flat-fielded exactly once."

2. **Sigma sweep** (see above) — quick, do after/independent of the bug fix, to land
   a candidate clip+sigma pair by eye.

3. **Ground truth** — hand-transcribe ~6–10 clean lines of one page (read-back
   discipline; note normalization rules). Blocks CER. Slow, human, do it fresh.

4. **CER measurement** — raw vs enhanced vs bleed-subtracted-enhanced, same page,
   same Transkribus model, `jiwer`. Blocked on #1 (bug fix) **and** #3 (ground
   truth). This is the citable result for the article. (Method already written up in a
   saved CER guide.)

5. **The web app** (v1/v2/v3) — see plan below. The active new ambition.

6. Later/additive: yellow-paper test sample (exercises the b* channel path);
   batch-enhance mode; Orsha annotation lines 4–6 (needs shelfmark/edition — separate
   research track).

---

## The web app — staged build plan (eat the elephant in pieces)

**Goal (eventual):** a local drag-and-drop app to render a PDF, tune sigma/clip with
live preview, optionally run bleed-through, compare (incl. one-glyph DIFF), and
download PNGs for Transkribus. **This is 5 capabilities, so build it in 3 layers,
each shipped working and committed before the next.** First app ever — go slow.

**Non-negotiable guardrails for every layer (from CLAUDE.md):**
- The app is a **face over `src/`** — it *imports* the existing functions and must
  **never reimplement or copy** the enhancement/bleed/verify math.
- Every uploaded file goes through **`validate_file()`** before anything else. The
  upload handler is the highest-risk entry point.
- No threshold/binarize step. Sharpen output stays a labelled pointer.
- Runs locally (`python app.py`), no external hosting.
- Review only two things in each diff: (a) does upload hit the gate, (b) does it
  import from `src/` rather than inline the math. UI/layout = vibecode freely.

### App v1 — the tuning core (BUILD THIS FIRST)
Upload a page (or a PDF, rendered once), two sliders (**sigma ~40–80**, **clip
~2–5**), live compare **original vs enhanced**, **download** the enhanced PNG.
Everything else hardcoded to defaults. This is the piece actually needed now to
finish the sigma/clip tuning.
- Expect slider lag (full-res enhance per change). If sluggish, preview on a
  downscaled copy and only run full-res on download.

### App v2 — add glyph verification
A crop selector that runs `verify_glyph` and shows the green/red DIFF inline.
Additive, self-contained, low-risk (surfaces a trusted script).

### App v3 — add the bleed-through branch (LAST, most care)
Two-file input (recto + verso), both gated. Must mirror the CLAUDE.md workflow
**exactly**: subtract on the **raw recto+verso**, *then* enhance — **never** on an
already-enhanced image; loop back to compare. This is the state-complex layer;
give it its own focused session and review the ordering against CLAUDE.md.

---

## Start here next (concrete first moves)

Pick the thread; each has a ready prompt.

**If continuing the app (likely):** build v1.
> *Read CLAUDE.md, src/enhance.py, and src/ingest.py. Build app.py: a local Gradio
> drag-and-drop app for tuning enhancement parameters. On image drop: pass the file
> through validate_file() first (reject cleanly with a message if it fails), then
> show original and enhanced side by side, with sliders for --sigma (40–80) and
> --clip (2–5) that re-run enhancement live. Import the enhancement functions from
> src/ — do NOT reimplement or copy the enhancement math, and do not add a
> threshold/binarize step. Include a button to save the current enhanced image to
> outputs/ and show the current sigma/clip values. Runs locally (python app.py). Then
> tell me how to launch it. Build ONLY this (v1) — no bleed-through, no glyph
> verification, no CER; those are later layers.*

**If fixing the blocker first (recommended before CER):**
> *Read CLAUDE.md and src/bleed_subtract.py and src/enhance.py. There is a double
> flat-field bug: bleed_subtract flat-fields internally and enhance flat-fields again
> on the _bleedremoved.png, and flat-field is non-idempotent (~9-unit stroke shift,
> proven by a strength=0 control). Fix so flat-field happens exactly once: keep
> internal flat-field only for k-estimation/alignment, but apply subtraction to the
> original colour recto and output an un-flat-fielded colour image, so enhance.py
> does the single flat-field. Add a test asserting a _bleedremoved.png through
> enhance.py is flat-fielded exactly once. Don't change the offset search, k formula,
> or --strength semantics. Run pytest and show results.*

**If running the sigma sweep:**
> *Run the clip/sigma sweep on my raw rendered test page (outputs/pages, Attendo p21),
> fixing clip at 3.0 and sweeping sigma at 40, 60, 80. Show the command, then run it
> and tell me where each output landed.*

---

## Standing habits (don't drop these)
- **One knob at a time** when tuning — or you can't attribute the effect.
- **Don't overfit:** the tuning piece is a dev set; ideally report CER on a page you
  didn't tune on. Simplest config that clearly helps > lowest possible number.
- **Commit at green**, with a message that says what changed (flag math changes).
- **Review-then-approve** every Claude Code action; small tasks = small diffs.
- **Read-back rule** for every actual reading: confirm in the untouched original.
- Source scans live **outside** the repo; only git-ignored renders under `outputs/`.
