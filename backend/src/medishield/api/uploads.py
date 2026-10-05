"""Upload hardening: magic-byte type detection, size / count / page limits, decompression-bomb guard.

Nothing here trusts the filename or the client's Content-Type. Accepted inputs (PNG, JPEG, PDF, TIFF) are
normalised into page images; image uploads are stored byte-for-byte (so the content hash is the user's
file), PDFs and multi-page TIFFs are rendered to one PNG per page.
"""

from __future__ import annotations

import hashlib
import io
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError

from medishield.config import get_settings

MAGIC = {"png": b"\x89PNG\r\n\x1a\n", "jpeg": b"\xff\xd8\xff", "pdf": b"%PDF-"}
TIFF_MAGIC = (b"II*\x00", b"MM\x00*")
PDF_RENDER_DPI = 150
MAX_PDF_PAGE_POINTS = 5000            # per side (72 points = 1 inch)


class UploadError(ValueError):
    """Rejected upload. ``status`` is the HTTP status the API should return."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass
class Page:
    doc_id: str
    filename: str
    data: bytes
    media_type: str
    sha256: str
    page: int = 1


def detect_type(data: bytes) -> str:
    for kind, magic in MAGIC.items():
        if data.startswith(magic):
            return kind
    if data.startswith(TIFF_MAGIC):
        return "tiff"
    raise UploadError("unsupported file type (accepted: PNG, JPEG, PDF, TIFF - detected by content, not extension)", 415)


def safe_stem(filename: str) -> str:
    stem = Path(filename or "document").stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:60]
    return stem or "document"


def _check_image(data: bytes) -> tuple[int, int]:
    """Decode the header and enforce a pixel budget before anything decodes the full image."""
    s = get_settings()
    Image.MAX_IMAGE_PIXELS = s.max_image_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                w, h = im.size
                if w * h > s.max_image_pixels:
                    raise UploadError(f"image too large: {w}x{h} exceeds {s.max_image_pixels:,} pixels")
                if w < 64 or h < 64:
                    raise UploadError("image too small to be a document")
                im.verify()
                return w, h
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        raise UploadError("rejected: decompression bomb") from e
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise UploadError("corrupt or unreadable image") from e


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _pdf_pages(data: bytes) -> list[bytes]:
    s = get_settings()
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as e:                                   # pypdfium2 raises PdfiumError
        raise UploadError("corrupt or unreadable PDF") from e
    try:
        n = len(pdf)
        if n == 0:
            raise UploadError("PDF has no pages")
        if n > s.max_pdf_pages:
            raise UploadError(f"PDF has {n} pages; the limit is {s.max_pdf_pages}")
        out = []
        for i in range(n):
            w, h = pdf[i].get_size()
            if w > MAX_PDF_PAGE_POINTS or h > MAX_PDF_PAGE_POINTS:
                raise UploadError("PDF page dimensions exceed the limit")
            scale = PDF_RENDER_DPI / 72
            if w * h * scale * scale > s.max_image_pixels:
                raise UploadError("PDF page would render beyond the pixel limit")
            out.append(_png(pdf[i].render(scale=scale).to_pil()))
        return out
    finally:
        pdf.close()


def _tiff_pages(data: bytes) -> list[bytes]:
    s = get_settings()
    Image.MAX_IMAGE_PIXELS = s.max_image_pixels
    try:
        with Image.open(io.BytesIO(data)) as im:
            n = getattr(im, "n_frames", 1)
            if n > s.max_pdf_pages:
                raise UploadError(f"TIFF has {n} frames; the limit is {s.max_pdf_pages}")
            out = []
            for i in range(n):
                im.seek(i)
                if im.width * im.height > s.max_image_pixels:
                    raise UploadError("TIFF frame exceeds the pixel limit")
                out.append(_png(im))
            return out
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        raise UploadError("rejected: decompression bomb") from e
    except (UnidentifiedImageError, OSError, EOFError, SyntaxError) as e:
        raise UploadError("corrupt or unreadable TIFF") from e


def normalise(filename: str, data: bytes, taken: set[str]) -> list[Page]:
    """Validate one uploaded file and return its page images (``taken`` = doc ids already used in the case)."""
    s = get_settings()
    if not data:
        raise UploadError("empty file")
    if len(data) > s.max_upload_bytes:
        raise UploadError(f"file exceeds {s.max_upload_bytes // (1024 * 1024)} MB", 413)
    kind = detect_type(data)
    stem = safe_stem(filename)
    if kind in ("png", "jpeg"):
        _check_image(data)
        pages = [(data, "image/png" if kind == "png" else "image/jpeg")]
    elif kind == "pdf":
        pages = [(p, "image/png") for p in _pdf_pages(data)]
    else:
        pages = [(p, "image/png") for p in _tiff_pages(data)]
    out = []
    for i, (blob, media) in enumerate(pages, 1):
        doc_id = stem if len(pages) == 1 else f"{stem}_p{i}"
        base, n = doc_id, 2
        while doc_id in taken:
            doc_id, n = f"{base}_{n}", n + 1
        taken.add(doc_id)
        out.append(Page(doc_id, filename, blob, media, hashlib.sha256(blob).hexdigest(), i))
    return out
