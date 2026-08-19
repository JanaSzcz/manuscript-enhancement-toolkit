---
description: Start the manuscript-page workflow ritual at Stage 1 (Baseline)
argument-hint: [PDF path] [--pages N] [--dpi 400]
---

Begin the "Session workflow (the ritual)" defined in `CLAUDE.md`, starting at
**Stage 1: Baseline**. Follow it exactly — do not skip, reorder, or merge
stages, and do not run ahead of the mandatory stop point at Stage 3 (Compare).

Page/input for this run: $ARGUMENTS
(If empty, ask which PDF/page to process before doing anything else.)

Stage 1 — Baseline:
- Activate the venv.
- Run `pytest -q` and report the result plainly (green or red).
- **Red → STOP.** Report the failure and wait for the human. Do not attempt a
  fix or proceed to Stage 2 in the same turn unless asked to.
- **Green → proceed automatically** to Stage 2 (Convert & Enhance), without
  asking first — a green baseline is standing permission for that one step.

After Stage 1, continue exactly as `CLAUDE.md` specifies for Stages 2-5:
2. Convert & Enhance (`src/pdf_to_png.py` then `src/enhance.py`, one chained
   action, no stop point between them).
3. Compare — MANDATORY HUMAN CHECK. Surface the `*_safe_*_BEST.png` output
   and the untouched original, then explicitly present three options and
   stop — do not assume which one the human wants, even if the enhancement
   looks obviously fine:
     1. Confirm it's trustworthy → go to Stage 4.
     2. Bleed-subtract → run `src/bleed_subtract.py` on the ORIGINAL
        recto+verso scans (never on the `*_safe_*_BEST.png` - bleed removal
        must happen before contrast is maximized). This loops back, it does
        not move forward: bleed-subtract → re-run `src/enhance.py` on the
        resulting `*_bleedremoved.png` → return to the top of Stage 3 with
        the new enhanced output. Do not proceed to Stage 4 from here.
     3. Verify a specific word → jump to Stage 4 for just that word via
        `src/verify_glyph.py`, without confirming the whole page yet.
   Do not run `verify_glyph.py`, `src/bleed_subtract.py`, or interpret any
   content in the same turn as presenting these options.
4. Read / verify — reached by confirming at Stage 3, or by choosing "verify
   a specific word" there. Use `src/verify_glyph.py` on the contested word(s).
5. Commit — only at a green baseline, and only with a commit message the
   human has approved.

End every reply made during this workflow by stating which stage the session
is currently on and naming the single next step.
