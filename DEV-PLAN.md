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

**Enhancement tuning status (as of 2026-09-13):**
- Clip sweep done by eye: **5.0 too much**; candidates **2.5 / 3.0 / 3.5**; 3.0–3.5
  look crisper but bring **more background noise**. No value committed as new default
  yet.
- Sigma sweep **now run**, via the app (see below) instead of the CLI. **Finding:
  sigma has negligible effect on these pages** — 40–50 all look fine by eye. **Keep
  sigma at the default 40**; changing it isn't earned.
- **Candidate clip: ~3.0–3.5** (crisper than the current 2.5 default). Exact value
  within that range is a background-noise tolerance call, not yet settled.
- **These are eyeball candidates on one page (Attendo p21), PENDING CER
  confirmation.** Do **not** change `enhance.py`'s defaults yet — the winning
  config gets decided by CER (raw vs enhanced vs bleed-subtracted-enhanced against
  ground truth; see blockers #3–#4 below), not by eye.
- Sharpen/upscale lever: **leave alone** (fabrication risk) unless clip+sigma prove
  insufficient, and only then with the DIFF check.
- Tooling used: **`app.py` (v1)** — the Gradio drag-and-drop tuner with live
  sigma/clip sliders — is what this sweep was actually run through, in place of
  the CLI `clip_sweep.py`-style loop originally planned. See "App v1" below.

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

2. ~~**Sigma sweep**~~ — **done** (see "Enhancement tuning status" above): sigma
   doesn't matter for these pages, keep it at 40; clip candidate ~3.0–3.5, pending
   CER before it becomes the new default.

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

### App v1 — the tuning core — **BUILT**
`app.py`: drop a PNG page, two live sliders (**sigma 40–80**, **clip 2–5**),
original vs enhanced side by side, save-to-`outputs/` button with sigma/clip
baked into the filename. Used to run the sigma sweep (see "Enhancement tuning
status" above). Everything else still hardcoded to defaults, as scoped.

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

**If continuing the app (likely):** build v2 (app v1 is done — see above).
> *Read CLAUDE.md and app.py. Add glyph verification (app v2): a crop selector
> that runs src/verify_glyph.py and shows the green/red DIFF panel inline.
> Additive, self-contained — import from src/, don't reimplement the DIFF math.*

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

**If running the sigma sweep:** done — see "Enhancement tuning status" above
(run through `app.py`'s live sliders rather than the CLI). Sigma stays at 40;
clip candidate ~3.0–3.5 is pending CER, not yet a default change.

---

## Standing habits (don't drop these)
- **One knob at a time** when tuning — or you can't attribute the effect.
- **Don't overfit:** the tuning piece is a dev set; ideally report CER on a page you
  didn't tune on. Simplest config that clearly helps > lowest possible number.
- **Commit at green**, with a message that says what changed (flag math changes).
- **Review-then-approve** every Claude Code action; small tasks = small diffs.
- **Read-back rule** for every actual reading: confirm in the untouched original.
- Source scans live **outside** the repo; only git-ignored renders under `outputs/`.
