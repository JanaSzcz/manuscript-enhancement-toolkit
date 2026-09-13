#!/usr/bin/env python3
"""
app.py - local Gradio drag-and-drop app for tuning enhancement parameters.

v1 scope only (see CLAUDE.md / DEV-PLAN.md "App v1 - the tuning core"):
  * drop a PNG page
  * every upload goes through src/ingest.py's validate_file() gate FIRST -
    a rejected file shows its reason in the UI and is never decoded further
  * two live sliders, --sigma (40-80) and --clip (2-5), re-run the enhancement
    and update the enhanced panel
  * a save button writes the currently-shown enhanced PNG into outputs/,
    with sigma/clip baked into the filename

This file is a thin UI wrapper: it IMPORTS the enhancement math from src/
enhance.py (enhance_page()) and never reimplements, copies, or modifies it.
No threshold/binarize step is added here. No PDF handling, no bleed-through,
no glyph verification - those are later layers.

Run:
  python app.py
"""
import os
import sys

import cv2
import gradio as gr
import numpy as np

# --- compatibility shim -----------------------------------------------------
# gradio==5.9.1's pinned gradio_client==1.5.2 (see requirements.txt) has a bug
# in its OpenAPI-schema-to-python-type stringifier: it crashes on ANY app
# where a File/Image-type component appears as both an input and an output
# somewhere in the graph - exactly this app's original-in/enhanced-out shape,
# via a raw JSON-Schema `additionalProperties: true` boolean it doesn't
# expect. That crash happens inside building the auto-generated API docs,
# but it's invoked unconditionally on every load of "/" (gradio/routes.py),
# so it 500s the whole UI, not just the docs page. Reproduced with a minimal
# two-component gr.Blocks app with no code of ours involved - this is an
# upstream bug, not a symptom of anything else here. Patching it here (rather
# than bumping the pinned gradio/gradio_client versions) keeps the
# reproducibility-pinned requirements.txt untouched. Only affects how a type
# is described in the (unused) auto-generated API docs string - never touches
# actual image data or the enhancement pipeline.
import gradio_client.utils as _gradio_client_utils  # noqa: E402

_orig_json_schema_to_python_type = _gradio_client_utils._json_schema_to_python_type


def _json_schema_to_python_type_patched(schema, defs):
    if isinstance(schema, bool):
        return "Any"
    return _orig_json_schema_to_python_type(schema, defs)


_gradio_client_utils._json_schema_to_python_type = _json_schema_to_python_type_patched
# --- end compatibility shim -------------------------------------------------

# src/enhance.py imports ingest.py as a sibling module (`from ingest import
# ...`), not as a package - so src/ must be on sys.path the same way it is
# when enhance.py is run directly as a script.
SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
sys.path.insert(0, SRC_DIR)

from enhance import enhance_page  # noqa: E402  (safe-enhancement math lives here, not in this file)
from ingest import validate_file, IngestRejected  # noqa: E402  (the one shared ingestion gate)

OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")

SIGMA_MIN, SIGMA_MAX, SIGMA_DEFAULT = 40, 80, 40
CLIP_MIN, CLIP_MAX, CLIP_DEFAULT = 2, 5, 2.5


def _bgr_to_display(gray_or_bgr):
    """cv2 arrays are BGR; Gradio's gr.Image expects RGB. Handles both the
    grayscale enhanced output and the color original."""
    if gray_or_bgr.ndim == 2:
        return gray_or_bgr
    return cv2.cvtColor(gray_or_bgr, cv2.COLOR_BGR2RGB)


def on_upload(file_path):
    """Runs on every drop/upload. validate_file() is the gate: nothing below
    it may decode the file if the gate raises."""
    if file_path is None:
        return (
            None,  # state: validated bgr original
            None,  # state: validated basename (for save filenames)
            None,  # original image panel
            None,  # enhanced image panel
            gr.update(value="", visible=False),  # error box
            gr.update(interactive=False),  # sigma slider
            gr.update(interactive=False),  # clip slider
            gr.update(interactive=False),  # save button
            "",  # values readout
            "",  # save status
        )

    try:
        validated = validate_file(file_path)
    except IngestRejected as e:
        return (
            None,
            None,
            None,
            None,
            gr.update(value=f"**Rejected by ingestion gate:** {e}", visible=True),
            gr.update(interactive=False),
            gr.update(interactive=False),
            gr.update(interactive=False),
            "",
            "",
        )

    if validated.kind != "png":
        return (
            None,
            None,
            None,
            None,
            gr.update(
                value=f"**Rejected:** app v1 only accepts PNG; got `{validated.kind}`.",
                visible=True,
            ),
            gr.update(interactive=False),
            gr.update(interactive=False),
            gr.update(interactive=False),
            "",
            "",
        )

    bgr = cv2.imread(str(validated.path))
    if bgr is None:
        return (
            None,
            None,
            None,
            None,
            gr.update(value="**Rejected:** file passed validation but could not be decoded by OpenCV.", visible=True),
            gr.update(interactive=False),
            gr.update(interactive=False),
            gr.update(interactive=False),
            "",
            "",
        )

    cand, best = enhance_page(bgr, SIGMA_DEFAULT, CLIP_DEFAULT)
    enhanced = cand[best]

    return (
        bgr,
        validated.safe_basename,
        _bgr_to_display(bgr),
        _bgr_to_display(enhanced),
        gr.update(value="", visible=False),
        gr.update(interactive=True, value=SIGMA_DEFAULT),
        gr.update(interactive=True, value=CLIP_DEFAULT),
        gr.update(interactive=True),
        f"sigma = {SIGMA_DEFAULT:g}   clip = {CLIP_DEFAULT:g}   channel = {best}",
        "",
    )


def on_params_change(bgr, sigma, clip):
    """Re-runs the safe enhancement live as either slider moves. No-ops
    (returns nothing changed) if no validated image is loaded yet."""
    if bgr is None:
        return gr.update(), ""
    cand, best = enhance_page(bgr, sigma, clip)
    enhanced = cand[best]
    return _bgr_to_display(enhanced), f"sigma = {sigma:g}   clip = {clip:g}   channel = {best}"


def on_save(bgr, basename, sigma, clip):
    if bgr is None:
        return "Nothing to save yet - drop a page first."

    cand, best = enhance_page(bgr, sigma, clip)
    enhanced = cand[best]

    os.makedirs(OUTDIR, exist_ok=True)
    stem = os.path.splitext(basename or "page")[0]
    filename = f"{stem}_safe_{best}_sigma{sigma:g}_clip{clip:g}.png"
    out_path = os.path.join(OUTDIR, filename)

    # cv2.imwrite picks the codec from the extension - ".png" writes a real,
    # lossless 8-bit PNG (never WebP/JPEG), matching CLAUDE.md's "output stays
    # 8-bit single-channel grayscale PNG" invariant and what Transkribus expects.
    ok = cv2.imwrite(out_path, enhanced)
    if not ok:
        return f"Save failed for {filename}."
    return f"Saved: outputs/{filename}"


with gr.Blocks(title="Manuscript Enhancement Tuner") as demo:
    gr.Markdown("# Manuscript enhancement tuner (v1)")
    gr.Markdown(
        "Drop a PNG page. Every upload is validated by `src/ingest.py` before "
        "anything is decoded. Tune `sigma` / `clip` live; save the enhanced "
        "PNG you're currently looking at to `outputs/`."
    )

    error_box = gr.Markdown(value="", visible=False)

    file_input = gr.File(
        label="Drop a manuscript page (PNG)",
        file_types=[".png"],
        type="filepath",
    )

    with gr.Row():
        # format="png": gr.Image defaults its internal file format to "webp"
        # for its own preview/download affordance (the small download icon on
        # the component) - that's separate from the save_button below, but
        # every path an image can leave this app through must stay lossless
        # PNG (Transkribus expects PNG; WebP risks degrading faint ink), so
        # override it here too.
        original_panel = gr.Image(label="Original", interactive=False, format="png")
        enhanced_panel = gr.Image(label="Enhanced (safe)", interactive=False, format="png")

    with gr.Row():
        sigma_slider = gr.Slider(
            minimum=SIGMA_MIN, maximum=SIGMA_MAX, value=SIGMA_DEFAULT, step=1,
            label="--sigma (flat-field blur)", interactive=False,
        )
        clip_slider = gr.Slider(
            minimum=CLIP_MIN, maximum=CLIP_MAX, value=CLIP_DEFAULT, step=0.1,
            label="--clip (CLAHE clip limit)", interactive=False,
        )

    values_readout = gr.Markdown(value="")

    save_button = gr.Button("Save enhanced PNG to outputs/", interactive=False)
    save_status = gr.Markdown(value="")

    # state: the validated, decoded original (BGR ndarray) and its safe
    # basename - never the raw uploaded path or filename again after this.
    bgr_state = gr.State(value=None)
    basename_state = gr.State(value=None)

    file_input.upload(
        fn=on_upload,
        inputs=[file_input],
        outputs=[
            bgr_state,
            basename_state,
            original_panel,
            enhanced_panel,
            error_box,
            sigma_slider,
            clip_slider,
            save_button,
            values_readout,
            save_status,
        ],
    )

    sigma_slider.change(
        fn=on_params_change,
        inputs=[bgr_state, sigma_slider, clip_slider],
        outputs=[enhanced_panel, values_readout],
    )
    clip_slider.change(
        fn=on_params_change,
        inputs=[bgr_state, sigma_slider, clip_slider],
        outputs=[enhanced_panel, values_readout],
    )

    save_button.click(
        fn=on_save,
        inputs=[bgr_state, basename_state, sigma_slider, clip_slider],
        outputs=[save_status],
    )


if __name__ == "__main__":
    demo.launch()
