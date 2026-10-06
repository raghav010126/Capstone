"""Human review: overrides with reason codes, four-eyes approval for high-value cases, reclassification.

Rules
* An override needs a reason code (a free-text note is mandatory for ``OTHER``).
* If the case's claimed amount exceeds ``four_eyes_amount`` the override is only *requested*; a different
  senior reviewer (or admin) must approve it. Nobody can approve their own request.
* Applying an override to a case paused at the graph's human-review node resumes the graph from its
  persisted checkpoint; overriding an already auto-decided case just records the new final decision.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status

from medishield import pipeline
from medishield.api.security import Principal, Role
from medishield.config import get_settings
from medishield.db import audit
from medishield.db.models import Override
from medishield.db.repo import Repo
from medishield.records import get_records
from medishield.schemas import Decision, DocType

REASON_CODES = {
    "CONFIRMED_AI_DECISION": "Reviewed; the automated decision is correct",
    "DOCUMENT_VERIFIED_MANUALLY": "Document verified manually / out of band",
    "ADDITIONAL_INFORMATION": "Additional information received from the member or provider",
    "FALSE_POSITIVE_FRAUD": "Fraud signal reviewed and dismissed",
    "CONFIRMED_FRAUD": "Fraud signal confirmed",
    "POLICY_EXCEPTION": "Coverage exception granted under policy",
    "EXTRACTION_ERROR": "Automated extraction misread the document",
    "CLASSIFICATION_ERROR": "Document was classified incorrectly",
    "OTHER": "Other (note required)",
}
OVERRIDABLE = {"IN_REVIEW", "DECIDED", "FINALIZED"}


def _utc() -> datetime:
    return datetime.now(UTC)


def request_override(db: Repo, user: Principal, case, decision: str, reason_code: str,
                     note: str):
    if reason_code not in REASON_CODES:
        raise HTTPException(422, f"unknown reason_code; use one of {sorted(REASON_CODES)}")
    if decision not in {d.value for d in Decision}:
        raise HTTPException(422, "decision must be APPROVE, REJECT or ESCALATE")
    if reason_code == "OTHER" and len(note.strip()) < 10:
        raise HTTPException(422, "a note of at least 10 characters is required for reason_code OTHER")
    if case.status not in OVERRIDABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"case is {case.status}; it cannot be overridden yet")
    pending = db.pending_override(case.id)
    if pending:
        raise HTTPException(status.HTTP_409_CONFLICT, f"override #{pending.id} is already awaiting approval")
    four_eyes = case.total_amount > get_settings().four_eyes_amount
    ov = Override(case_id=case.id, requested_by=user.username, decision=decision, reason_code=reason_code,
                  note=note.strip()[:1000], ai_decision=case.ai_decision, amount=case.total_amount,
                  requires_four_eyes=four_eyes, status="PENDING_APPROVAL")
    ov = db.add_override(ov)
    audit.append(db, user.username, "override_requested", case.id,
                 {"override_id": ov.id, "decision": decision, "reason_code": reason_code, "amount": case.total_amount,
                  "four_eyes": four_eyes, "note": ov.note})
    if not four_eyes:
        _apply(db, case, ov, user.username)
    return ov


def approve_override(db: Repo, user: Principal, case, ov):
    if ov.status != "PENDING_APPROVAL":
        raise HTTPException(status.HTTP_409_CONFLICT, f"override is already {ov.status}")
    if ov.requested_by == user.username:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "four-eyes: you cannot approve your own override")
    if user.role not in (Role.SENIOR_REVIEWER, Role.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "approval requires a senior reviewer")
    audit.append(db, user.username, "override_approved", case.id, {"override_id": ov.id})
    _apply(db, case, ov, user.username)
    return ov


def reject_override(db: Repo, user: Principal, case, ov, note: str):
    if ov.status != "PENDING_APPROVAL":
        raise HTTPException(status.HTTP_409_CONFLICT, f"override is already {ov.status}")
    if ov.requested_by == user.username:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "four-eyes: you cannot decide your own override")
    ov.status, ov.resolved_by, ov.resolved_at = "REJECTED", user.username, _utc()
    db.save_override(ov)
    audit.append(db, user.username, "override_rejected", case.id, {"override_id": ov.id, "note": note[:300]})
    return ov


def _apply(db: Repo, case, ov, resolver: str) -> None:
    # On Lambda there is no durable disk for the graph checkpoint: the override is recorded and the case finalised without resuming it
    was_waiting = case.status == "IN_REVIEW" and case.thread_id and get_settings().queue_backend not in ("sqs", "agentcore")
    ov.status, ov.resolved_by, ov.resolved_at = "APPLIED", resolver, _utc()
    case.final_decision, case.status = ov.decision, "FINALIZED"
    db.save_override(ov)
    db.save_case(case)
    if was_waiting:                         # resume the paused graph from its checkpoint
        pipeline.resume_case(case.thread_id, {"decision": ov.decision, "reason": ov.reason_code,
                                              "reviewer": ov.requested_by, "approved_by": resolver},
                             # same session: a second connection would wait on this request's open write lock
                             lambda ev: db.add_event(case.id, ev))
    audit.append(db, resolver, "override_applied", case.id,
                 {"override_id": ov.id, "from": case.ai_decision, "to": ov.decision, "reason_code": ov.reason_code,
                  "resumed_graph": bool(was_waiting)})


def reclassify(db: Repo, user: Principal, case, doc_id: str, doc_type: str, reason_code: str,
               note: str):
    """Force a document's type and re-run the case (LLM responses are cached, so only changed steps cost)."""
    if doc_type not in {t.value for t in DocType}:
        raise HTTPException(422, f"doc_type must be one of {[t.value for t in DocType]}")
    if reason_code not in REASON_CODES:
        raise HTTPException(422, f"unknown reason_code; use one of {sorted(REASON_CODES)}")
    if case.status in ("RECEIVED", "PROCESSING"):
        raise HTTPException(status.HTTP_409_CONFLICT, "case is still processing")
    doc = next((d for d in case.documents if d.doc_id == doc_id), None)
    if doc is None:
        raise HTTPException(404, "document not found in this case")
    audit.append(db, user.username, "document_reclassified", case.id,
                 {"doc_id": doc_id, "from": doc.doc_type, "to": doc_type, "reason_code": reason_code, "note": note[:300]})
    doc.forced_type = doc_type
    db.save_document(doc)
    case.status, case.final_decision, case.thread_id = "PROCESSING", None, f"{case.id}-{uuid.uuid4().hex[:8]}"
    db.save_case(case)
    get_records().unregister_case(case.id)
    return case
