"""Email -> case: who may send, which SES checks must pass, and the audit trail.

Sender mapping: an explicit allow-list (``INTAKE_SENDERS``, a JSON object ``{"address": "username"}``). It is the
smallest thing that is safe: no schema change, nothing guessed from display names, one place to revoke a sender, and an
empty list rejects everything. The mapped user must exist, be active and hold ``case:create``.

Every rejection is written to the audit chain as ``email_rejected`` with the channel, the sender's *domain* and a reason
that never contains message content (no local part, subject or file names). Rejected mail is never parsed further.
"""

from __future__ import annotations

from medishield.api.security import Principal, Role
from medishield.api.uploads import UploadError
from medishield.db import audit
from medishield.db.models import Case
from medishield.db.repo import Repo
from medishield.intake.email import ParsedEmail
from medishield.intake.settings import intake_settings
from medishield.services import cases as svc

VERDICTS = ("spf", "dkim", "dmarc", "spam", "virus")


def domain_of(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def resolve_sender(db: Repo, address: str) -> Principal:
    """The user an allow-listed sender submits as; anything else raises ``UploadError`` (403)."""
    username = intake_settings().senders.get(address.strip().lower()) if address else None
    if not username:
        raise UploadError("sender is not on the intake allow-list", 403)
    u = db.get_user(username)
    if u is None or not u.active:
        raise UploadError("sender is mapped to an unknown or disabled user", 403)
    user = Principal(u.username, Role(u.role), u.display_name)
    if not user.can("case:create"):
        raise UploadError("sender is mapped to a user who may not create cases", 403)
    return user


def verdict_failures(receipt: dict) -> list[str]:
    """SES receipt verdicts that are not PASS. A verdict that is absent or DISABLED (scanning off) is not available and
    is skipped; GRAY and PROCESSING_FAILED count as failures, so spoofed or unauthenticated mail is never processed."""
    bad = []
    for name in VERDICTS:
        v = receipt.get(f"{name}Verdict")
        status = str((v or {}).get("status", "")).upper()
        if v is None or status == "DISABLED":
            continue
        if status != "PASS":
            bad.append(f"{name}={status or 'MISSING'}")
    return bad


def submit(db: Repo, owner: Principal, parsed: ParsedEmail, channel: str) -> tuple[Case, list[str], bool]:
    """Create (or, for a message seen before, return) the case. Same validation and idempotency as an upload."""
    if not parsed.attachments:
        raise UploadError("the message has no PDF, PNG, JPEG or TIFF attachment", 422)
    case, warnings, created = svc.create_case(db, owner, parsed.attachments, parsed.idempotency_key)
    if created:
        audit.append(db, owner.username, "case_created_by_email", case.id,
                     {"channel": channel, "sender_domain": parsed.sender_domain, "message_ref": parsed.ref[:16],
                      "attachments": len(parsed.attachments), "skipped_parts": len(parsed.skipped)})
    return case, ([*parsed.skipped, *warnings] if created else []), created


def reject(db: Repo, actor: str, channel: str, sender_domain: str, reason: str, **extra) -> None:
    audit.append(db, actor, "email_rejected", None,
                 {"channel": channel, "sender_domain": sender_domain, "reason": reason[:200], **extra})
