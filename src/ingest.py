#!/usr/bin/env python3
"""
ingest.py - the ONE shared validation gate for every file this toolkit reads.

CLAUDE.md, "Ingestion protection": every file the toolkit ingests - dragged
into the app, passed on the CLI, or discovered in a batch folder - is
UNTRUSTED until it passes through validate_file(). No other code path may
decode a file that hasn't gone through this gate first.

This module is intentionally standalone: it has no dependency on app.py or
the CLI scripts, and nothing in the repo calls it yet. That wiring is a
separate change.

What it guards against:
  * wrong file types (checked by content, not just extension)
  * oversized files
  * decompression-bomb images / PDFs (huge decoded pixel counts from a tiny
    file)
  * path-traversal via a hostile filename
  * any decode that fails, hangs the parser, or half-crashes the process

Everything downstream should treat a ValidatedFile as the only trustworthy
handle on an ingested file, and should build output paths only through
resolve_output_path() - never by touching the original filename directly.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image
import pypdfium2 as pdfium

# --- configurable limits ----------------------------------------------------
# These are deliberately generous for real manuscript scans (a 400 DPI page
# is typically well under 50 MP) but tight enough to stop a tiny malicious
# file from claiming to be a gigapixel image or a thousand-page PDF.

MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024   # 100 MB, checked before any decode
MAX_IMAGE_MEGAPIXELS = 120                 # ~ e.g. 11000 x 11000
MAX_PDF_PAGES = 500
MAX_PDF_RENDER_SCALE = 1200 / 72.0         # cap: never render a sanity page above ~1200 DPI

# Let Pillow's own decompression-bomb guard back up our explicit check below.
# (Pillow raises outright above 2x this value, and warns between 1x-2x; our
# own megapixel check after Image.open() is what actually enforces the cap.)
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_MEGAPIXELS * 1_000_000

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}

_EXT_TO_KIND = {
    ".pdf": "pdf",
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".tif": "tiff",
    ".tiff": "tiff",
}

# Magic-byte signatures used to verify actual file content, independent of
# whatever extension the file claims to have.
_MAGIC_SIGNATURES = {
    b"%PDF-": "pdf",
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
    b"II*\x00": "tiff",   # little-endian ("Intel") TIFF
    b"MM\x00*": "tiff",   # big-endian ("Motorola") TIFF
}
_MAGIC_SNIFF_LEN = max(len(sig) for sig in _MAGIC_SIGNATURES)


class IngestRejected(Exception):
    """Raised for any file that fails the validation gate. Always carries a
    human-readable reason. Callers should catch this specifically and skip
    the file (log-and-continue in batch mode, show a message in the app) -
    never let it propagate as a crash."""


@dataclass(frozen=True)
class ValidatedFile:
    """Handle on a file that has passed the gate. Downstream code should
    treat this - not the raw path or filename - as the source of truth."""
    path: Path            # original on-disk location; fine to open, never to build output paths from
    kind: str              # "pdf" | "png" | "jpeg" | "tiff", confirmed by content
    safe_basename: str      # sanitized basename, safe to use in output filenames
    sha256: str            # provenance hash of the raw input bytes
    size_bytes: int
    dimensions: Optional[tuple] = None   # (width, height) for images; None for PDFs (varies per page)
    page_count: Optional[int] = None      # for PDFs; None for images


# --- filename safety ---------------------------------------------------------

def sanitize_basename(name: str) -> str:
    """Reduce an arbitrary, possibly-hostile filename to a safe basename.

    Strips directory components (handles both '/' and '\\' separators, so
    this is safe even when running on a platform that wouldn't otherwise
    treat '\\' as a separator), drops leading dots (so '..', '.', and
    dotfiles can't sneak through), and keeps only a conservative charset.
    Never returns something containing '/', '\\', or '..'.
    """
    # Normalize both separator styles before taking the last component, so
    # "..\\..\\evil.png" can't survive by hiding behind the "wrong" slash.
    normalized = name.replace("\\", "/")
    candidate = normalized.split("/")[-1]
    candidate = candidate.lstrip(".")
    safe = "".join(c for c in candidate if c.isalnum() or c in "._-")
    safe = safe.strip("._-")
    if not safe:
        raise IngestRejected(f"filename has no safe characters after sanitizing: {name!r}")
    return safe


def resolve_output_path(validated: ValidatedFile, suffix: str, outdir: str | Path = "outputs") -> Path:
    """Build an output path from a VALIDATED file's sanitized basename -
    never from a raw incoming filename. Always resolves inside `outdir`;
    raises IngestRejected if that's somehow not the case (defense in depth -
    sanitize_basename() should already make this unreachable).
    """
    outdir_path = Path(outdir).resolve()
    outdir_path.mkdir(parents=True, exist_ok=True)
    base = Path(validated.safe_basename).stem
    out_path = (outdir_path / f"{base}{suffix}").resolve()
    if outdir_path != out_path and outdir_path not in out_path.parents:
        raise IngestRejected(f"refusing to write outside {outdir_path}: {out_path}")
    return out_path


# --- internal checks -----------------------------------------------------

def _check_size(path: Path) -> int:
    size = path.stat().st_size
    if size == 0:
        raise IngestRejected(f"file is empty: {path.name}")
    if size > MAX_FILE_SIZE_BYTES:
        raise IngestRejected(
            f"{path.name}: {size / 1e6:.1f} MB exceeds the {MAX_FILE_SIZE_BYTES / 1e6:.0f} MB size cap"
        )
    return size


def _detect_kind_from_content(path: Path) -> Optional[str]:
    with open(path, "rb") as f:
        header = f.read(_MAGIC_SNIFF_LEN)
    for magic, kind in _MAGIC_SIGNATURES.items():
        if header.startswith(magic):
            return kind
    return None


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_raster_image(path: Path, kind: str) -> tuple:
    """Safe-decode an image file and enforce the pixel/dimension cap.
    Returns (width, height) on success; raises IngestRejected otherwise.
    """
    try:
        with Image.open(path) as im:
            # A PNG/JPEG/TIFF header gives the declared size without
            # decoding pixel data, so this check happens BEFORE we ever ask
            # for the full pixel buffer - the key defense against a tiny
            # file that claims to be a gigapixel image.
            w, h = im.size
            megapixels = (w * h) / 1_000_000
            if megapixels > MAX_IMAGE_MEGAPIXELS:
                raise IngestRejected(
                    f"{path.name}: declared size {w}x{h} ({megapixels:.0f} MP) exceeds the "
                    f"{MAX_IMAGE_MEGAPIXELS} MP cap - refusing to decode (possible decompression bomb)"
                )
            # Only now do the full decode, and only inside this try/except.
            im.load()
    except IngestRejected:
        raise
    except Image.DecompressionBombError as e:
        raise IngestRejected(f"{path.name}: rejected by Pillow's decompression-bomb guard: {e}") from e
    except Exception as e:
        raise IngestRejected(f"{path.name}: could not decode as {kind}: {e}") from e
    return (w, h)


def _validate_pdf(path: Path) -> int:
    """Safe-open a PDF, cap its page count, and sanity-render page 1 at a
    conservative scale with annotations off to catch malformed/bomb PDFs
    before any real processing happens. Returns the page count.
    """
    try:
        doc = pdfium.PdfDocument(str(path))
        n_pages = len(doc)
    except Exception as e:
        raise IngestRejected(f"{path.name}: could not open as PDF: {e}") from e

    if n_pages == 0:
        raise IngestRejected(f"{path.name}: PDF has no pages")
    if n_pages > MAX_PDF_PAGES:
        raise IngestRejected(f"{path.name}: {n_pages} pages exceeds the {MAX_PDF_PAGES}-page cap")

    try:
        page = doc[0]
        # draw_annots=False: never execute/render embedded annotation
        # content. scale=1.0 keeps the sanity render cheap regardless of
        # what render scale a caller might later request.
        pil = page.render(scale=1.0, draw_annots=False).to_pil()
        w, h = pil.size
        megapixels = (w * h) / 1_000_000
        if megapixels > MAX_IMAGE_MEGAPIXELS:
            raise IngestRejected(
                f"{path.name}: page 1 renders to {w}x{h} ({megapixels:.0f} MP) at 1x scale, "
                f"exceeding the {MAX_IMAGE_MEGAPIXELS} MP cap"
            )
    except IngestRejected:
        raise
    except Exception as e:
        raise IngestRejected(f"{path.name}: could not render as PDF: {e}") from e

    return n_pages


# --- the gate ------------------------------------------------------------

def validate_file(path) -> ValidatedFile:
    """The shared ingestion gate. Every file this toolkit reads - from the
    app, the CLI, or a batch folder - must pass through this before any
    code path decodes it for real.

    Raises IngestRejected (never anything else) with a clear reason on
    anything suspicious. Never writes anything, so there is nothing to
    clean up on rejection.
    """
    path = Path(path)

    if not path.is_file():
        raise IngestRejected(f"not a file: {path}")

    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise IngestRejected(
            f"{path.name}: unsupported file type {ext!r} (allowed: {sorted(ALLOWED_EXTENSIONS)})"
        )

    size = _check_size(path)

    kind = _detect_kind_from_content(path)
    if kind is None:
        raise IngestRejected(
            f"{path.name}: file content doesn't match any supported format "
            f"(pdf/png/jpeg/tiff magic bytes not found) - extension alone is not trusted"
        )

    expected_kind = _EXT_TO_KIND[ext]
    if kind != expected_kind:
        raise IngestRejected(
            f"{path.name}: extension {ext!r} claims {expected_kind!r} but content is actually "
            f"{kind!r} - refusing to guess which is right"
        )

    dimensions = None
    page_count = None
    if kind == "pdf":
        page_count = _validate_pdf(path)
    else:
        dimensions = _validate_raster_image(path, kind)

    return ValidatedFile(
        path=path,
        kind=kind,
        safe_basename=sanitize_basename(path.name),
        sha256=_sha256_of(path),
        size_bytes=size,
        dimensions=dimensions,
        page_count=page_count,
    )
