"""Case lifecycle: create from uploads, run the pipeline, persist results, rebuild the claim registry."""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from medishield import pipeline
from medishield.api.security import Principal, redact
from medishield.api.uploads import Page, UploadError, normalise
from medishield.config import get_settings
from medishield.db import audit
from medishield.db.models import AgentRunRow, Case, CaseEvent, Document
from medishield.db.session import session_scope
from medishield.fraud.rules import norm_claim_no
from medishield.llm import BudgetExceeded
from medishield.records import ProcessedClaim, get_records
from medishield.schemas import DocType
from medishield.storage.base import get_storage

log = logging.getLogger(__name__)


def new_case_id() -> str:
    return "CASE-" + secrets.token_hex(4).upper()


def display_status(c: Case) -> str:
    if c.status in ("RECEIVED", "PROCESSING"):
        return "Processing"
    if c.status == "FAILED":
        return "Failed"
    if c.status == "IN_REVIEW":
        return "Escalated"
    final = c.final_decision or c.ai_decision
    return {"APPROVE": "Approved", "REJECT": "Rejected", "ESCALATE": "Escalated"}.get(final or "", "Processing")


def sla_due(c: Case) -> datetime:
    created = c.created_at if c.created_at.tzinfo else c.created_at.replace(tzinfo=UTC)
    return created + timedelta(hours=get_settings().sla_hours)


# ── creation ─────────────────────────────────────────────────────────────────────────────────────────
def create_case(db: Session, user: Principal, files: list[tuple[str, bytes]],
                idempotency_key: str | None) -> tuple[Case, list[str], bool]:
    """Validate, store and register a case. Returns (case, warnings, created). Idempotent per
    (submitter, Idempotency-Key): a retried request returns the original case instead of a second one."""
    s = get_settings()
    if idempotency_key:
        prior = db.execute(select(Case).where(Case.submitted_by == user.username,
                                              Case.idempotency_key == idempotency_key)).scalar_one_or_none()
        if prior:
            return prior, [], False
    if not files:
        raise UploadError("no files uploaded", 422)
    if len(files) > s.max_files_per_case:
        raise UploadError(f"at most {s.max_files_per_case} files per case", 413)

    taken: set[str] = set()
    seen: dict[str, str] = {}
    pages: list[Page] = []
    warnings: list[str] = []
    for filename, data in files:
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:                                     # same bytes twice in one upload
            warnings.append(f"{filename}: identical to {seen[digest]}; ignored")
            continue
        seen[digest] = filename
        pages.extend(normalise(filename, data, taken))
    if len(pages) > s.max_files_per_case * s.max_pdf_pages:
        raise UploadError("too many pages in this case", 413)

    case = Case(id=new_case_id(), submitted_by=user.username, idempotency_key=idempotency_key, status="RECEIVED")
    storage = get_storage()
    for i, pg in enumerate(pages):
        ext = "jpg" if pg.media_type == "image/jpeg" else "png"
        key = f"cases/{case.id}/{pg.doc_id}.{ext}"
        storage.put(key, pg.data, pg.media_type)
        case.documents.append(Document(doc_id=pg.doc_id, position=i, filename=pg.filename[:255], storage_key=key,
                                       media_type=pg.media_type, size_bytes=len(pg.data), sha256=pg.sha256,
                                       page=pg.page))
    db.add(case)
    try:
        db.flush()
    except IntegrityError:                                     # lost an idempotency race
        db.rollback()
        prior = db.execute(select(Case).where(Case.submitted_by == user.username,
                                              Case.idempotency_key == idempotency_key)).scalar_one()
        return prior, [], False
    audit.append(db, user.username, "case_created", case.id,
                 {"documents": [d.doc_id for d in case.documents], "sha256": [d.sha256[:16] for d in case.documents]})
    return case, warnings, True


# ── events ───────────────────────────────────────────────────────────────────────────────────────────
def event_row(case_id: str, ev: dict) -> CaseEvent:
    extra = {k: v for k, v in ev.items() if k not in ("node", "status", "doc_id", "ts")}
    return CaseEvent(case_id=case_id, node=str(ev.get("node", "")), status=str(ev.get("status", "")),
                     doc_id=ev.get("doc_id"), payload=extra)


def emit(case_id: str, ev: dict) -> None:
    """Record a progress event in its own short transaction (worker use)."""
    with session_scope() as db:
        db.add(event_row(case_id, ev))


# ── running the pipeline ─────────────────────────────────────────────────────────────────────────────
def case_total(docs: list[Document]) -> float:
    seen, total = set(), 0.0
    for d in docs:
        if d.doc_type == DocType.CLAIM_FORM.value and d.extraction:
            v = d.extraction["values"]
            key = norm_claim_no(v.get("claim_number")) or d.doc_id
            if key not in seen and v.get("total_charge"):
                seen.add(key)
                total += float(v["total_charge"])
    return round(total, 2)


def rebuild_registry() -> int:
    """Re-create the processed-claims registry (duplicate detection) from stored extractions after a restart."""
    records = get_records()
    n = 0
    with session_scope() as db:
        rows = db.execute(select(Document, Case.created_at).join(Case, Case.id == Document.case_id)
                          .where(Document.doc_type == DocType.CLAIM_FORM.value, Document.extraction.is_not(None),
                                 Case.status.in_(("DECIDED", "IN_REVIEW", "FINALIZED")))
                          .order_by(Case.created_at, Document.position)).all()
        for d, _ in rows:
            v = d.extraction["values"]
            member, _how = records.find_member(policy=v.get("policy_number"), name=v.get("patient_name"),
                                               dob=v.get("patient_dob"))
            records.register(ProcessedClaim(d.doc_id, d.case_id, norm_claim_no(v.get("claim_number")),
                                            member["member_id"] if member else None, v.get("service_date"),
                                            v.get("total_charge"), d.image_hash))
            n += 1
    return n


def process_case(case_id: str) -> None:
    """Worker entry point: run the graph for a stored case and persist the outcome."""
    storage = get_storage()
    with session_scope() as db:
        case = db.get(Case, case_id)
        if case is None:
            return
        case.status, case.error = "PROCESSING", None
        case.thread_id = f"{case_id}-{uuid.uuid4().hex[:8]}"
        thread_id = case.thread_id
        paths = [(d.doc_id, storage.local_path(d.storage_key)) for d in case.documents]
        forced = {d.doc_id: d.forced_type for d in case.documents if d.forced_type}
    get_records().unregister_case(case_id)
    emit(case_id, {"node": "queued", "status": "running"})
    try:
        out = pipeline.run_case_stream(case_id, paths, thread_id, lambda ev: emit(case_id, ev), forced)
    except BudgetExceeded as e:
        _fail(case_id, f"LLM budget reached: {e}")
        return
    except Exception as e:
        log.exception("case %s failed", case_id)
        _fail(case_id, f"{type(e).__name__}: {redact(str(e))[:300]}")
        return
    with session_scope() as db:
        persist_result(db, db.get(Case, case_id), out["values"], out["paused"], out["wall_ms"])


def _fail(case_id: str, message: str) -> None:
    with session_scope() as db:
        case = db.get(Case, case_id)
        case.status, case.error = "FAILED", message[:500]
        audit.append(db, "system", "case_failed", case_id, {"error": message[:200]})
    emit(case_id, {"node": "failed", "status": "error", "error": message[:200]})


def persist_result(db: Session, case: Case, values: dict[str, Any], paused: bool, wall_ms: float) -> None:
    dec = values["decision"]
    by_doc = {d["doc_id"]: d for d in dec["documents"]}
    for d in case.documents:
        p, sp = values["perception"].get(d.doc_id, {}), values["specialists"].get(d.doc_id, {})
        d.classification, d.quality = p.get("classification"), p.get("quality")
        d.doc_type = (p.get("classification") or {}).get("doc_type")
        d.extraction, d.image_hash = p.get("extraction"), p.get("image_hash")
        d.specialists = sp
        dd = by_doc.get(d.doc_id)
        d.decision, d.decision_detail = (dd["decision"] if dd else None), dd
    runs = values.get("runs", [])
    db.query(AgentRunRow).filter(AgentRunRow.case_id == case.id).delete()
    for r in runs:
        db.add(AgentRunRow(case_id=case.id, agent=r["agent"], model=r.get("model"), retried_with=r.get("retried_with"),
                           input_tokens=r["input_tokens"], output_tokens=r["output_tokens"], cost_usd=r["cost_usd"],
                           latency_ms=r["latency_ms"], llm_calls=r["llm_calls"], cache_hits=r["cache_hits"]))
    fraud = values.get("fraud") or {}
    case.decision, case.fraud = dec, fraud
    case.ai_decision, case.ai_confidence = dec["decision"], dec["confidence"]
    case.risk_score = fraud.get("fraud_score", 0.0)
    case.total_amount = case_total(case.documents)
    case.wall_ms, case.cost_usd = wall_ms, round(sum(r["cost_usd"] for r in runs), 4)
    case.final_decision = None if paused else dec["decision"]
    case.status = "IN_REVIEW" if paused else "DECIDED"
    audit.append(db, "system", "case_decided", case.id,
                 {"decision": dec["decision"], "confidence": dec["confidence"], "needs_review": paused,
                  "rules": {d["doc_id"]: d["rule_id"] for d in dec["documents"]}})
