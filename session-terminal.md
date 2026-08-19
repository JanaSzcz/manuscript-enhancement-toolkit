# Session guide — Terminal

What to do, in order, every time you sit down to process or test a real page from
a plain terminal. Copy-paste friendly. Assumes you're in the project folder.

---

## 0. Start-of-session ritual (always, in this order)

```bash
cd path/to/manuscript-htr-toolkit     # go to the repo

source .venv/bin/activate             # macOS / Linux
# .venv\Scripts\activate              # Windows (PowerShell)

git status                            # know your state before touching anything
pytest -q                             # confirm a GREEN baseline first
```

**Why this order:** you always want to *know the code is healthy* (green tests)
and *know your git state* before you start, so if something breaks later you can
tell whether it was you or something already broken. If `pytest` is not green,
stop and fix that before doing anything else — don't build on a red baseline.

---

## 1. Get one real page as PNG

If you have the PDF:

```bash
python src/pdf_to_png.py your_manuscript.pdf --dpi 400 --outdir outputs/pages
```

One PNG per page lands in `outputs/pages/`. If you already have a PNG, skip this
and use that file directly.

> Real scans go in `outputs/` (git-ignored), **never** in `samples/`. `samples/`
> is only the tiny synthetic test image.

---

## 2. Enhance that page

```bash
python src/enhance.py outputs/pages/your_manuscript_p021.png --outdir outputs/enhanced
```

(Use the real filename from step 1.) This writes into `outputs/enhanced/`:
- `*_safe_..._BEST.png`  ← the one you READ from
- the other channel candidate
- `*_pointer_sharp.png`  ← a hint only, never read from this

**Check the printed line.** It says which channel it picked and the contrast
scores, e.g. `blue=54.6 bstar=43.9`. On a *yellow* page you'd expect `bstar` to
win. If the winner looks worse to your eye than the loser, open the other channel
file and use that one — the auto-pick is a default, not a verdict.

---

## 3. Look at the results (this IS the test)

Open the files in your file browser (Finder / Explorer) and double-click, or use
any image viewer. There is no green "PASSED" here — **your eyes are the check.**

Go in this order:
1. Open `*_safe_..._BEST.png`. Can you read more faded ink than in the original?
   Good — the tool is working.
2. Open the **original** scan beside it.
3. **The read-back rule:** anything you think you can read in the enhanced image,
   go find it in the original. If it's there (just fainter) → trust it. If a
   stroke exists in the enhanced image with **no trace at all** in the original →
   the tool invented it → discard that reading.
4. Treat `*_pointer_sharp.png` only as "look here," never as evidence.

---

## 4. Vet a single uncertain word

When one word carries the reading, check just that spot:

```bash
python src/verify_glyph.py outputs/pages/your_manuscript_p021.png 0.55 0.10 0.35 0.16 --frac
```

The four numbers are a rough box: start 55% across, 10% down, 30% wide, 16% tall.
Nudge them until the crop lands on your word. You get a RAW / SAFE / SHARP / DIFF
strip.

**Reading the DIFF panel:** green on the strokes = fine (revealed real ink);
green on blank paper = the tool made something up there → don't trust it.

---

## 5. End-of-session ritual — commit at green

Only commit when tests are green and you're at a sensible stopping point:

```bash
pytest -q                             # still green?
git status                            # review what changed
git add -A
git commit -m "docs: process page 21, notes on lines 4-6"
```

Committing at green checkpoints (not randomly) means you can always return to
solid ground. Never commit `outputs/` or full-res scans — `.gitignore` handles
this, but glance at `git status` to be sure.

---

## Quick reference (the whole flow)

```bash
cd path/to/manuscript-htr-toolkit
source .venv/bin/activate
git status && pytest -q
python src/pdf_to_png.py your_manuscript.pdf --dpi 400 --outdir outputs/pages
python src/enhance.py outputs/pages/PAGE.png --outdir outputs/enhanced
# → eyeball: enhanced vs original, apply the read-back rule
python src/verify_glyph.py outputs/pages/PAGE.png 0.55 0.10 0.35 0.16 --frac
git add -A && git commit -m "..."     # only at green
```

**The two questions this workflow answers, kept separate:**
- `pytest` → "did I accidentally break the code?"
- your eyes → "is the tool helping me read *this* page, without lying?"
