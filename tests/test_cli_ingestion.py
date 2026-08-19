"""
tests/test_cli_ingestion.py — end-to-end proof that each of the three CLI
scripts actually calls the shared ingestion gate at its entry point, per
CLAUDE.md's "Ingestion protection" section: a known-bad file must be refused
by the SCRIPT (non-zero exit, no crash, no output written), not merely by
src/ingest.py in isolation (see tests/test_ingest.py for that).

Each test shells out to the real script via subprocess, exactly as a user
would invoke it from the CLI.

Run: pytest -q
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"


def make_impostor_png(path: Path) -> Path:
    """A file with an allowed extension whose actual content is not that
    format at all - the canonical 'known-bad' fixture: it should sail past
    a naive extension check but be caught by the content-based gate."""
    path.write_bytes(b"this is plain text wearing a .png extension\n" * 3)
    return path


def run_script(script_name, args):
    cmd = [sys.executable, str(SRC / script_name)] + [str(a) for a in args]
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


def test_pdf_to_png_refuses_bad_file(tmp_path):
    # pdf_to_png.py takes a positional "pdf" arg but the gate validates by
    # actual extension/content, not by which script is asking - a non-PDF
    # file must still be refused before any pdfium call is attempted.
    bad = make_impostor_png(tmp_path / "fake.png")
    outdir = tmp_path / "pages_out"
    result = run_script("pdf_to_png.py", [bad, "--outdir", outdir])

    assert result.returncode != 0, f"expected non-zero exit, got 0. stdout={result.stdout!r}"
    assert "REJECTED" in result.stderr
    assert "Traceback" not in result.stderr, "script crashed instead of exiting cleanly"
    assert not outdir.exists() or not any(outdir.iterdir()), "no output should be written for a rejected file"


def test_enhance_refuses_bad_file(tmp_path):
    bad = make_impostor_png(tmp_path / "fake.png")
    outdir = tmp_path / "enhanced_out"
    result = run_script("enhance.py", [bad, "--outdir", outdir])

    assert result.returncode != 0, f"expected non-zero exit, got 0. stdout={result.stdout!r}"
    assert "REJECTED" in result.stderr
    assert "Traceback" not in result.stderr, "script crashed instead of exiting cleanly"
    assert not outdir.exists() or not any(outdir.iterdir()), "no output should be written for a rejected file"


def test_verify_glyph_refuses_bad_file(tmp_path):
    bad = make_impostor_png(tmp_path / "fake.png")
    out_panel = tmp_path / "glyph_check.png"
    result = run_script("verify_glyph.py", [bad, "0.02", "0.1", "0.3", "0.15", "--frac", "--out", out_panel])

    assert result.returncode != 0, f"expected non-zero exit, got 0. stdout={result.stdout!r}"
    assert "REJECTED" in result.stderr
    assert "Traceback" not in result.stderr, "script crashed instead of exiting cleanly"
    assert not out_panel.exists(), "no output should be written for a rejected file"
