"""
tests/test_ingest.py — confirms the shared validation gate in src/ingest.py
rejects untrusted input cleanly, per CLAUDE.md's "Ingestion protection"
section. Nothing in the repo calls src/ingest.py yet; this only tests the
gate in isolation.

Run: pytest -q
"""
import sys
from pathlib import Path

import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "samples" / "sample_page.png"

sys.path.insert(0, str(REPO_ROOT / "src"))
import ingest  # noqa: E402


# --- sanity: the gate isn't just rejecting everything -----------------------

def test_accepts_a_legitimate_png():
    result = ingest.validate_file(SAMPLE)
    assert result.kind == "png"
    assert result.safe_basename == "sample_page.png"
    assert result.dimensions is not None and all(d > 0 for d in result.dimensions)
    assert len(result.sha256) == 64  # hex sha256
    assert result.size_bytes == SAMPLE.stat().st_size


# --- (a) wrong-type file -----------------------------------------------------

def test_rejects_disallowed_extension(tmp_path):
    bad = tmp_path / "payload.exe"
    bad.write_bytes(b"MZ\x90\x00 not an accepted type")
    with pytest.raises(ingest.IngestRejected, match="unsupported file type"):
        ingest.validate_file(bad)


def test_rejects_content_that_does_not_match_its_extension(tmp_path):
    # A file wearing an allowed extension but whose actual bytes are not
    # that format at all — the gate must check content, not just the name.
    impostor = tmp_path / "note.png"
    impostor.write_bytes(b"this is plain text, not a PNG\n" * 5)
    with pytest.raises(ingest.IngestRejected, match="doesn't match any supported format"):
        ingest.validate_file(impostor)


def test_rejects_extension_content_mismatch(tmp_path):
    # Real PDF magic bytes, but named as a .png — extension and content
    # disagree, so the gate must refuse to guess which one is right.
    mismatched = tmp_path / "sneaky.png"
    mismatched.write_bytes(b"%PDF-1.4\n%fake pdf body")
    with pytest.raises(ingest.IngestRejected, match="claims .* but content is actually"):
        ingest.validate_file(mismatched)


# --- (b) oversized file ------------------------------------------------------

def test_rejects_oversized_file(tmp_path, monkeypatch):
    # Patch the cap down instead of writing a real 100MB+ file, so the test
    # stays fast; the code path exercised is identical either way — size is
    # checked from stat() before any content is read.
    monkeypatch.setattr(ingest, "MAX_FILE_SIZE_BYTES", 1024)
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 5000)
    with pytest.raises(ingest.IngestRejected, match="exceeds the .* size cap"):
        ingest.validate_file(big)


def test_rejects_empty_file(tmp_path):
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    with pytest.raises(ingest.IngestRejected, match="empty"):
        ingest.validate_file(empty)


# --- (c) dimension / decompression-bomb image --------------------------------

def test_rejects_dimension_bomb_image(tmp_path):
    # Classic decompression-bomb shape: a solid-color image compresses to a
    # tiny file but claims an enormous pixel count. 15000x15000 = 225 MP,
    # comfortably over the module's 120 MP cap.
    bomb = tmp_path / "bomb.png"
    Image.new("1", (15000, 15000), 0).save(bomb, "PNG")
    assert bomb.stat().st_size < 100_000, "fixture should be a tiny file (that's the point of a bomb)"
    with pytest.raises(ingest.IngestRejected, match="MP cap"):
        ingest.validate_file(bomb)


def test_rejects_dimension_bomb_at_smaller_scale_via_patched_cap(tmp_path, monkeypatch):
    # Same check, but proves it triggers right at the configured boundary
    # rather than only for extreme sizes — patch the cap down and use an
    # otherwise-ordinary-sized image.
    monkeypatch.setattr(ingest, "MAX_IMAGE_MEGAPIXELS", 0.01)  # 10,000 px cap
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)  # disable Pillow's own guard so ours is what's tested
    ordinary = tmp_path / "ordinary.png"
    Image.new("L", (200, 200), 128).save(ordinary, "PNG")  # 0.04 MP, over the patched cap
    with pytest.raises(ingest.IngestRejected, match="MP cap"):
        ingest.validate_file(ordinary)


# --- (d) path-traversal filename ---------------------------------------------

@pytest.mark.parametrize("hostile_name", [
    "../../etc/passwd.png",
    "..\\..\\windows\\system32\\evil.png",
    "/etc/passwd",
    "....//....//escape.png",
    "a/../../../b.png",
])
def test_sanitize_basename_strips_traversal(hostile_name):
    safe = ingest.sanitize_basename(hostile_name)
    assert ".." not in safe
    assert "/" not in safe
    assert "\\" not in safe


@pytest.mark.parametrize("degenerate_name", ["..", "...", ".", "////"])
def test_sanitize_basename_rejects_names_with_nothing_safe_left(degenerate_name):
    with pytest.raises(ingest.IngestRejected):
        ingest.sanitize_basename(degenerate_name)


def test_resolve_output_path_stays_inside_outdir(tmp_path):
    validated = ingest.ValidatedFile(
        path=Path("irrelevant"),
        kind="png",
        safe_basename=ingest.sanitize_basename("../../../etc/passwd.png"),
        sha256="0" * 64,
        size_bytes=1,
    )
    outdir = tmp_path / "outputs"
    out_path = ingest.resolve_output_path(validated, "_safe.png", outdir=outdir)
    assert outdir.resolve() in out_path.parents
    assert ".." not in out_path.parts
