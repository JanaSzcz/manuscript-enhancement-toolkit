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
   and the untouched original, explicitly ask the human to confirm the
   enhancement is trustworthy, and stop. Do not proceed past this on your
   own for any reason, and do not run `verify_glyph.py` or interpret any
   content in the same turn.
4. Read / verify — only after the human confirms at Stage 3, use
   `src/verify_glyph.py` on the contested word(s).
5. Commit — only at a green baseline, and only with a commit message the
   human has approved.

End every reply made during this workflow by stating which stage the session
is currently on and naming the single next step.
