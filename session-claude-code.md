# Session guide — Claude Code

The same flow as the terminal guide, but driven through Claude Code. Here you
mostly type plain-language requests, and Claude Code proposes the commands and
edits — your job is to **review before you approve**, and to do the eyeball checks
yourself (a tool can't judge a reading of real handwriting for you).

---

## 0. Start-of-session ritual

```bash
cd path/to/manuscript-htr-toolkit
claude
```

Claude Code reads `CLAUDE.md` automatically at the start. Make a habit of
confirming that context actually loaded, and of establishing a green baseline,
with one opening message:

> *Summarize the safety invariants from CLAUDE.md in one line each, then activate
> the venv, run pytest, and show me the results.*

If it can't summarize the invariants, the project context didn't load — stop and
check you're in the right folder. If `pytest` isn't green, fix that first; don't
build on a red baseline.

**The golden habit:** Claude Code asks permission before it runs commands or edits
files. Read what it proposes *before* you approve. Approving without reading is how
beginners get into trouble; reviewing-then-approving is the whole skill.

---

## 1–2. Process a real page

Give it the task in plain language. It will propose the commands; check they point
at the right files, then approve.

> *I have a manuscript PDF at ~/Downloads/wapowski.pdf. Convert page 21 to a
> 400-DPI PNG into outputs/pages, then run the enhancement on it into
> outputs/enhanced. Tell me which channel it picked and the contrast scores. Don't
> change any code — just run the existing scripts.*

Things to check when it reports back:
- The filenames it used are the ones you meant.
- It tells you the chosen channel + scores (e.g. `blue=54.6 bstar=43.9`). On a
  *yellow* page, expect `bstar` to win — if the pick looks wrong, ask it to show
  you the other channel file too.

> Reminder: real scans belong in `outputs/` (git-ignored), never in `samples/`.
> If Claude Code ever proposes putting a real scan in `samples/`, say no — that
> violates CLAUDE.md.

---

## 3. Look at the results yourself (the real test)

This part is **not** something to delegate. Ask Claude Code to surface the images,
then judge with your own eyes:

> *Show me the enhanced BEST image and the original side by side.*

(In the desktop app you can open them in the file view; otherwise open
`outputs/enhanced/` in Finder / Explorer.)

Then apply the **read-back rule** yourself:
- Read what you can in the `*_safe_..._BEST.png`.
- Find each reading in the **original**. There but fainter → trust it. No trace in
  the original → the tool invented it → discard.
- `*_pointer_sharp.png` is a "look here" hint only, never evidence.

Claude Code can *describe* what it sees, but the final call on a reading is yours —
it's your discipline, and the scholarship, on the line.

---

## 4. Vet a single uncertain word

> *Run verify_glyph on page 21 for the word around 55% across, 10% down, roughly
> 30% wide and 16% tall. Show me the RAW / SAFE / SHARP / DIFF strip.*

You read the DIFF panel: green on strokes = fine; green on blank paper = fabricated
there, don't trust it. Ask it to nudge the box if the crop misses the word.

---

## 5. End-of-session ritual — commit at green

> *Run pytest. If it's green, show me git status, then stage everything and commit
> with a clear message describing what I did this session. Show me the commit
> message before you run it.*

Review the proposed message and the list of changed files **before** approving.
Never let it commit `outputs/` or full-res scans (`.gitignore` should prevent it —
a glance at `git status` confirms). Commit only at green checkpoints, so you can
always roll back to solid ground.

---

## The habits that matter most (in Claude Code specifically)

- **Review, then approve.** Every command and edit it proposes — read it first.
- **One task at a time.** Small, clear requests are easier to review than "do
  everything." Small steps = small diffs = easy to judge.
- **You own the readings.** pytest and Claude Code guard the *code*; only you can
  confirm the tool is reading *this page* honestly against the original.
- **Commit at green.** Same rule as the terminal — green tests, sensible stopping
  point, clear message.

**Two questions, kept separate:** pytest answers "did the code break?"; your eyes
answer "is the tool helping me read this page, without lying?"
