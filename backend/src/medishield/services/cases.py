"""Case lifecycle: create from uploads, run the pipeline, persist results, rebuild the claim registry."""

from __future__ import annotations

import hashlib
import logging
import math
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from medishield.api.security import Principal, redact
from medishield.api.uploads import Page, UploadError, normalise
from medishield.config import get_settings
from medishield.db import audit
from medishield.db.models import Case, Document
from medishield.db.repo import Repo, repo_scope
from medishield.fraud.rules import norm_claim_no
from medishield.llm.cost import BudgetExceeded
from medishield.records import ProcessedClaim, get_records
from medishield.schemas import DocType
from medishield.storage.base import get_storage

log = logging.getLogger(__name__)


def new_case_id() -> str:
    return "CASE-" + secrets.token_hex(4).upper()


def display_status(c) -> str:
    if c.status in ("RECEIVED", "PROCESSING"):
        return "Processing"
    if c.status == "FAILED":
        return "Failed"
    if c.status == "IN_REVIEW":
        return "Escalated"
    final = c.final_decision or c.ai_decision
    return {"APPROVE": "Approved", "REJECT": "Rejected", "ESCALATE": "Escalated"}.get(final or "", "Processing")


def sla_due(c) -> datetime:
    created = c.created_at if c.created_at.tzinfo else c.created_at.replace(tzinfo=UTC)
    return created + timedelta(hours=get_settings().sla_hours)


# ── creation ─────────────────────────────────────────────────────────────────────────────────────────
def create_case(db: Repo, user: Principal, files: list[tuple[str, bytes]],
                idempotency_key: str | None) -> tuple[Case, list[str], bool]:
    """Validate, store and register a case. Returns (case, warnings, created). Idempotent per
    (submitter, Idempotency-Key): a retried request returns the original case instead of a second one."""
    s = get_settings()
    if idempotency_key:
        prior = db.find_case_by_idempotency(user.username, idempotency_key)
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
    case, created = db.add_case(case)
    if not created:                                            # lost an idempotency race
        return case, [], False
    audit.append(db, user.username, "case_created", case.id,
                 {"documents": [d.doc_id for d in case.documents], "sha256": [d.sha256[:16] for d in case.documents]})
    return case, warnings, True


def should_enqueue(case, created: bool, stale_after_s: float = 60.0) -> bool:
    """Queue a new case, or re-queue a replayed one that is still RECEIVED a minute after creation - the first enqueue failed
    (e.g. the runtime throttled), and an idempotent retry must not leave it stuck."""
    if created:
        return True
    if getattr(case, "status", None) != "RECEIVED" or case.created_at is None:
        return False
    created_at = case.created_at if case.created_at.tzinfo else case.created_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - created_at).total_seconds() > stale_after_s


# ── events ───────────────────────────────────────────────────────────────────────────────────────────
def emit(case_id: str, ev: dict) -> None:
    """Record a progress event in its own short transaction (worker use)."""
    with repo_scope() as db:
        db.add_event(case_id, ev)


# ── running the pipeline ─────────────────────────────────────────────────────────────────────────────
def case_total(docs: list) -> float:
    seen, total = set(), 0.0
    for d in docs:
        if d.doc_type == DocType.CLAIM_FORM.value and d.extraction:
            v = d.extraction["values"]
            key = norm_claim_no(v.get("claim_number")) or d.doc_id
            amount = v.get("total_charge")
            if key not in seen and isinstance(amount, (int, float)) and math.isfinite(amount) and amount > 0:
                seen.add(key)
                total += amount
    return round(total, 2)


def rebuild_registry() -> int:
    """Re-create the processed-claims registry (duplicate detection) from stored extractions after a restart."""
    records = get_records()
    n = 0
    with repo_scope() as db:
        done = sorted((c for c in db.all_cases() if c.status in ("DECIDED", "IN_REVIEW", "FINALIZED")), key=lambda c: c.created_at)
        docs = []
        for c in done:                                         # list views carry document stubs; the registry needs the extractions
            full = db.get_case(c.id)
            docs += [d for d in sorted(full.documents, key=lambda d: d.position)
                     if d.doc_type == DocType.CLAIM_FORM.value and d.extraction]
        for d in docs:
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
    from medishield import pipeline  # imported here: the API never runs the graph, and it is slow to load

    storage = get_storage()
    with repo_scope() as db:
        case = db.get_case(case_id)
        if case is None:
            return
        case.status, case.error = "PROCESSING", None
        case.thread_id = f"{case_id}-{uuid.uuid4().hex[:8]}"
        thread_id = case.thread_id
        paths = [(d.doc_id, storage.local_path(d.storage_key)) for d in case.documents]
        forced = {d.doc_id: d.forced_type for d in case.documents if d.forced_type}
        db.save_case(case)
    get_records().unregister_case(case_id)
    with repo_scope() as db:                          # a re-run (e.g. after a reclassification) starts a fresh progress log
        db.clear_events(case_id)
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
    with repo_scope() as db:
        persist_result(db, db.get_case(case_id), out["values"], out["paused"], out["wall_ms"])


def _fail(case_id: str, message: str) -> None:
    with repo_scope() as db:
        case = db.get_case(case_id)
        case.status, case.error = "FAILED", message[:500]
        db.save_case(case)
        audit.append(db, "system", "case_failed", case_id, {"error": message[:200]})
    emit(case_id, {"node": "failed", "status": "error", "error": message[:200]})


def persist_result(db: Repo, case, values: dict[str, Any], paused: bool, wall_ms: float) -> None:
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
    db.replace_agent_runs(case.id, runs)
    fraud = values.get("fraud") or {}
    case.decision, case.fraud = dec, fraud
    case.ai_decision, case.ai_confidence = dec["decision"], dec["confidence"]
    case.risk_score = fraud.get("fraud_score", 0.0)
    case.total_amount = case_total(case.documents)
    case.wall_ms, case.cost_usd = wall_ms, round(sum(r["cost_usd"] for r in runs), 4)
    case.cold_cost_usd = round(sum(r.get("cold_cost_usd", r["cost_usd"]) for r in runs), 4)
    case.final_decision = None if paused else dec["decision"]
    case.status = "IN_REVIEW" if paused else "DECIDED"
    for d in case.documents:
        db.save_document(d)
    db.save_case(case)
    audit.append(db, "system", "case_decided", case.id,
                 {"decision": dec["decision"], "confidence": dec["confidence"], "needs_review": paused,
                  "rules": {d["doc_id"]: d["rule_id"] for d in dec["documents"]}})
