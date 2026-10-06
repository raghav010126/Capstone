"""Raw RFC 5322 message -> the files of a case.

A part is kept when it looks like a document by its declared type, its file extension or its magic bytes (PDF, PNG,
JPEG, TIFF). Body text and HTML, office files, calendar invites and other parts are skipped, and so are small inline
PNG/JPEG parts (logos and signature banners). Nothing here decides whether a kept part is acceptable: the files go
through ``services.cases.create_case`` -> ``api.uploads.normalise`` exactly like an upload, so content sniffing, the
size, page and pixel caps and the file-count limit all apply unchanged (a ``.pdf`` that is really an executable is
rejected with 415, as it would be on the upload form).
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import re
from dataclasses import dataclass, field
from email.utils import getaddresses
from pathlib import PurePath

from medishield.api.uploads import UploadError, detect_type
from medishield.intake.settings import intake_settings

DECLARED = {"application/pdf": "pdf", "application/x-pdf": "pdf", "image/png": "png", "image/jpeg": "jpeg",
            "image/jpg": "jpeg", "image/pjpeg": "jpeg", "image/tiff": "tiff", "image/tif": "tiff"}
EXTENSIONS = {".pdf": "pdf", ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".tif": "tiff", ".tiff": "tiff"}
SUFFIX = {"pdf": "pdf", "png": "png", "jpeg": "jpg", "tiff": "tif"}


@dataclass
class ParsedEmail:
    message_id: str                                     # as sent, without <>; "" when the message has none
    sender: str                                         # the single From address, lower-cased
    subject: str
    attachments: list[tuple[str, bytes]]                # (filename, bytes) in message order
    skipped: list[str] = field(default_factory=list)    # notes for the submitter (they may name files: never audit them)
    ref: str = ""                                       # sha256 of the Message-ID (of the whole message when it has none)

    @property
    def sender_domain(self) -> str:
        return self.sender.rsplit("@", 1)[-1]

    @property
    def idempotency_key(self) -> str:
        """The same Idempotency-Key mechanism as uploads: a re-delivered or re-submitted message returns the first case."""
        return f"email:{self.ref}"


def sender_of(values: list[str]) -> str:
    """The one address in a From header (several From headers or addresses are ambiguous and rejected)."""
    addrs = [a.strip().lower() for _name, a in getaddresses([str(v) for v in values]) if a.strip()]
    if len(addrs) != 1 or not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", addrs[0]):
        raise UploadError("the message must have exactly one valid From address", 422)
    return addrs[0]


def _kind(data: bytes) -> str | None:
    try:
        return detect_type(data)
    except UploadError:
        return None


def _clean_name(name: str | None) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "", name or "").strip()[:200]


def parse(raw: bytes, *, max_bytes: int | None = None, min_inline_image_bytes: int | None = None) -> ParsedEmail:
    cfg = intake_settings()
    max_bytes = cfg.max_email_bytes if max_bytes is None else max_bytes
    min_inline = cfg.min_inline_image_bytes if min_inline_image_bytes is None else min_inline_image_bytes
    if not raw:
        raise UploadError("empty message")
    if len(raw) > max_bytes:
        raise UploadError(f"message exceeds {max_bytes // (1024 * 1024)} MB", 413)
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        sender = sender_of(msg.get_all("from") or [])
        subject = str(msg.get("subject", "") or "")
        message_id = str(msg.get("message-id", "") or "").strip().strip("<>").strip()
        attachments, skipped = _documents(msg, min_inline)
    except UploadError:
        raise
    except Exception as e:                                     # malformed headers or parameters, absurd MIME nesting
        raise UploadError("unreadable email message") from e
    ref = hashlib.sha256(message_id.encode() if message_id else raw).hexdigest()[:40]
    return ParsedEmail(message_id, sender, subject, attachments, skipped, ref)


def _documents(msg, min_inline: int) -> tuple[list[tuple[str, bytes]], list[str]]:
    attachments: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    for n, part in enumerate(msg.walk(), 1):
        if part.is_multipart():
            continue
        ctype, disp = part.get_content_type(), part.get_content_disposition()
        name = _clean_name(part.get_filename())
        if ctype.startswith("text/") and disp != "attachment" and not name:
            continue                                           # the message body
        label = name or f"part {n} ({ctype})"
        try:
            data = part.get_payload(decode=True) or b""
        except (ValueError, TypeError):                        # undecodable transfer encoding
            data = b""
        sniffed = _kind(data)
        kind = sniffed or DECLARED.get(ctype) or EXTENSIONS.get(PurePath(name).suffix.lower())
        if kind is None:
            skipped.append(f"{label}: not a PDF, PNG, JPEG or TIFF document; skipped")
            continue
        if not data:
            skipped.append(f"{label}: empty; skipped")
            continue
        inline = disp == "inline" or (disp is None and part.get("content-id") is not None)
        if inline and kind in ("png", "jpeg") and len(data) < min_inline:
            skipped.append(f"{label}: small inline image (logo or signature); skipped")
            continue
        attachments.append((name or f"attachment-{len(attachments) + 1}.{SUFFIX[kind]}", data))
    return attachments, skipped
