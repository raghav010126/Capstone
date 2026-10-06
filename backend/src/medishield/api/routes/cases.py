from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse

from medishield.api import schemas as S
from medishield.api.deps import get_case, get_db, stream_user
from medishield.api.security import Principal, Role, client_key, limiter, principal_from_token, require
from medishield.api.uploads import UploadError
from medishield.config import get_settings
from medishield.db import audit
from medishield.db.repo import Repo, repo_scope
from medishield.llm.cost import BudgetExceeded, ledger  # not medishield.llm: that loads the model SDK
from medishield.schemas import (
    CaseDecision,
    ClaimsResult,
    Classification,
    DocumentDecision,
    ExtractedField,
    FraudResult,
    KycResult,
    PolicyResult,
    QualityMetrics,
)
from medishield.services import cases as svc
from medishield.storage.base import get_storage
from medishield.worker.queue import enqueue_case

router = APIRouter(tags=["cases"])
TERMINAL = {"DECIDED", "IN_REVIEW", "FINALIZED", "FAILED"}


def summary(c, pending: bool = False) -> S.CaseSummary:
    due = svc.sla_due(c)
    open_case = c.status == "IN_REVIEW"
    return S.CaseSummary(
        id=c.id, status=c.status, display_status=svc.display_status(c), ai_decision=c.ai_decision,
        final_decision=c.final_decision, confidence=c.ai_confidence, risk_score=c.risk_score,
        total_amount=c.total_amount, n_documents=len(c.documents), submitted_by=c.submitted_by,
        created_at=c.created_at, sla_due=due, sla_breached=open_case and datetime.now(UTC) > due,
        pending_override=pending, error=c.error)


def document_out(case_id: str, d) -> S.DocumentOut:
    ext, sp = d.extraction or {}, d.specialists or {}
    return S.DocumentOut(
        doc_id=d.doc_id, filename=d.filename, position=d.position, media_type=d.media_type, doc_type=d.doc_type,
        classification=Classification.model_validate(d.classification) if d.classification else None,
        quality=QualityMetrics.model_validate(d.quality) if d.quality else None,
        fields=[ExtractedField.model_validate(f) for f in ext.get("fields", [])],
        grounding_rate=ext.get("grounding_rate"), confidence=ext.get("confidence"),
        kyc=KycResult.model_validate(sp["kyc"]) if sp.get("kyc") else None,
        claims=ClaimsResult.model_validate(sp["claims"]) if sp.get("claims") else None,
        policy=PolicyResult.model_validate(sp["policy"]) if sp.get("policy") else None,
        decision=DocumentDecision.model_validate(d.decision_detail) if d.decision_detail else None,
        image_url=f"/cases/{case_id}/documents/{d.doc_id}/image", forced_type=d.forced_type)


def override_out(o) -> S.OverrideOut:
    return S.OverrideOut.model_validate(o, from_attributes=True)


def _admit(user: Principal) -> None:
    s = get_settings()
    limiter.check(f"upload:{user.username}", s.upload_rate_per_min)
    try:
        ledger().check()
        ledger().check_daily()
    except BudgetExceeded as e:
        raise HTTPException(503, f"processing is paused: {e}") from e


@router.post("/cases", response_model=S.CaseCreated, status_code=202)
async def create_case(request: Request, response: Response, files: list[UploadFile] = File(...),
                      idempotency_key: str | None = Header(default=None, max_length=128),
                      user: Principal = Depends(require("case:create")), db: Repo = Depends(get_db)):
    s = get_settings()
    _admit(user)
    blobs: list[tuple[str, bytes]] = []
    for f in files[: s.max_files_per_case + 1]:
        data = await f.read(s.max_upload_bytes + 1)                       # never buffer more than the cap
        blobs.append((f.filename or "document", data))
    return _create(request, response, user, db, blobs, idempotency_key)


@router.get("/cases/upload-mode", response_model=S.UploadMode)
def upload_mode(user: Principal = Depends(require("case:create"))):
    """Behind Lambda a request may carry at most 6 MB, so on AWS files go straight to S3 and the API reads them from there."""
    s = get_settings()
    return S.UploadMode(mode="presigned" if s.storage_backend == "s3" else "direct", max_file_bytes=s.max_upload_bytes,
                        max_files=s.max_files_per_case)


def _upload_prefix(user: Principal, upload_id: str) -> str:
    return f"uploads/{re.sub(r'[^A-Za-z0-9_-]', '_', user.username)}/{upload_id}/"


@router.post("/cases/uploads", response_model=S.UploadGrant)
def grant_uploads(body: S.UploadRequest, user: Principal = Depends(require("case:create"))):
    s = get_settings()
    if s.storage_backend != "s3":
        raise HTTPException(409, "direct uploads are only used with S3 storage; POST /cases instead")
    if len(body.files) > s.max_files_per_case:
        raise HTTPException(413, f"at most {s.max_files_per_case} files per case")
    too_big = [f.filename for f in body.files if f.size > s.max_upload_bytes]
    if too_big:
        raise HTTPException(413, f"larger than {s.max_upload_bytes // 1_000_000} MB: {', '.join(too_big)}")
    _admit(user)
    upload_id, storage = uuid.uuid4().hex, get_storage()
    targets = []
    for i, f in enumerate(body.files):
        key = _upload_prefix(user, upload_id) + f"{i:02d}-" + re.sub(r"[^\w.\- ]", "_", f.filename)[:120]
        post = storage.presign_post(key, s.max_upload_bytes)
        targets.append(S.UploadTarget(url=post["url"], fields=post["fields"], key=key))
    return S.UploadGrant(upload_id=upload_id, uploads=targets)


@router.post("/cases/from-uploads", response_model=S.CaseCreated, status_code=202)
def create_from_uploads(request: Request, response: Response, body: S.FromUploads,
                        idempotency_key: str | None = Header(default=None, max_length=128),
                        user: Principal = Depends(require("case:create")), db: Repo = Depends(get_db)):
    """Create a case from files the browser uploaded with /cases/uploads. Only the caller's own upload prefix is read."""
    s, storage = get_settings(), get_storage()
    if s.storage_backend != "s3":
        raise HTTPException(409, "direct uploads are only used with S3 storage")
    keys = storage.list_prefix(_upload_prefix(user, body.upload_id))[: s.max_files_per_case + 1]
    if not keys:
        raise HTTPException(404, "no uploaded files for this upload id")
    blobs = [(k.rsplit("/", 1)[-1].split("-", 1)[-1], storage.get(k)) for k in keys]
    for k in keys:
        storage.delete(k)
    return _create(request, response, user, db, blobs, idempotency_key)


def _create(request: Request, response: Response, user: Principal, db: Repo, blobs: list[tuple[str, bytes]],
            idempotency_key: str | None) -> S.CaseCreated:
    try:
        case, warnings, created = svc.create_case(db, user, blobs, idempotency_key)
    except UploadError as e:
        audit.append(db, user.username, "upload_rejected", None, {"reason": str(e)[:200], "ip": client_key(request)})
        db.commit()
        raise HTTPException(e.status, str(e)) from e
    db.commit()
    if svc.should_enqueue(case, created):
        enqueue_case(case.id)
    if not created:
        response.status_code = 200
    return S.CaseCreated(case_id=case.id, status=case.status, documents=[d.doc_id for d in case.documents],
                         warnings=warnings, idempotent_replay=not created)


@router.get("/cases", response_model=list[S.CaseSummary])
def list_cases(status: str | None = None, decision: str | None = None, limit: int = Query(50, le=200),
               offset: int = 0, user: Principal = Depends(require("case:read")), db: Repo = Depends(get_db)):
    cases = db.list_cases(submitted_by=user.username if user.role == Role.SUBMITTER else None, status=status, decision=decision,
                          limit=limit, offset=offset)
    pending = db.case_ids_with_override_status("PENDING_APPROVAL")
    return [summary(c, c.id in pending) for c in cases]


@router.get("/cases/{case_id}", response_model=S.CaseDetail)
def case_detail(case_id: str, user: Principal = Depends(require("case:read")), db: Repo = Depends(get_db)):
    c = get_case(db, user, case_id)
    runs = db.list_agent_runs(c.id)
    ovs = db.list_overrides(c.id)
    base = summary(c, any(o.status == "PENDING_APPROVAL" for o in ovs)).model_dump()
    return S.CaseDetail(
        **base, decision=CaseDecision.model_validate(c.decision) if c.decision else None,
        fraud=FraudResult.model_validate(c.fraud) if c.fraud else None,
        documents=[document_out(c.id, d) for d in c.documents],
        agent_runs=[S.AgentRunOut.model_validate(r, from_attributes=True) for r in runs],
        overrides=[override_out(o) for o in ovs], wall_ms=c.wall_ms, cost_usd=c.cost_usd,
        cold_cost_usd=c.cold_cost_usd)


@router.get("/cases/{case_id}/documents/{doc_id}/image")
def document_image(case_id: str, doc_id: str, user: Principal = Depends(require("case:read")),
                   db: Repo = Depends(get_db)):
    c = get_case(db, user, case_id)
    d = next((x for x in c.documents if x.doc_id == doc_id), None)
    if d is None:
        raise HTTPException(404, "document not found")
    audit.append(db, user.username, "document_viewed", c.id, {"doc_id": doc_id})
    return Response(get_storage().get(d.storage_key), media_type=d.media_type,
                    headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@router.get("/cases/{case_id}/documents/{doc_id}/ela")
def document_ela(case_id: str, doc_id: str, user: Principal = Depends(require("case:read")), db: Repo = Depends(get_db)):
    """Error Level Analysis heatmap for a JPEG document (computed on demand; other file types have no compression history)."""
    from medishield.forensics import ela

    c = get_case(db, user, case_id)
    d = next((x for x in c.documents if x.doc_id == doc_id), None)
    if d is None:
        raise HTTPException(404, "document not found")
    res = ela.analyse(get_storage().get(d.storage_key))
    if not res.applicable or res.heatmap_png is None:
        raise HTTPException(404, "no ELA for this file type: only JPEG files carry compression history")
    audit.append(db, user.username, "document_viewed", c.id, {"doc_id": doc_id, "view": "ela"})
    return Response(res.heatmap_png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


def _events_after(case_id: str, last: int) -> tuple[list[S.EventOut], str | None]:
    with repo_scope() as db:
        rows = db.events_after(case_id, last)
        case = db.case_header(case_id)
        return [S.EventOut.model_validate(r, from_attributes=True) for r in rows], (case.status if case else None)


@router.get("/cases/{case_id}/progress", response_model=S.CaseProgress)
def case_progress(case_id: str, after: int = Query(0, ge=0), user: Principal = Depends(require("case:read")),
                  db: Repo = Depends(get_db)):
    """New events since ``after`` plus the case status, in one cheap call (for UIs that poll instead of streaming)."""
    head = db.case_header(case_id)
    if head is None or (user.role == Role.SUBMITTER and head.submitted_by != user.username):
        raise HTTPException(404, "case not found")
    return S.CaseProgress(events=[S.EventOut.model_validate(r, from_attributes=True) for r in db.events_after(case_id, after)],
                          status=head.status)


@router.get("/cases/{case_id}/events", response_model=list[S.EventOut])
def case_events(case_id: str, user: Principal = Depends(require("case:read")), db: Repo = Depends(get_db)):
    get_case(db, user, case_id)
    return _events_after(case_id, 0)[0]


async def _event_stream(case_id: str, poll: float = 0.4, max_seconds: float = 900):
    """Yield events as they are written; stops once the case reaches a terminal state and the log is drained."""
    last, waited = 0, 0.0
    while waited < max_seconds:
        events, status = await asyncio.to_thread(_events_after, case_id, last)
        for ev in events:
            last = ev.id
            yield {"type": "event", **json.loads(ev.model_dump_json())}
        if status in TERMINAL and not events:
            yield {"type": "done", "status": status}
            return
        await asyncio.sleep(poll)
        waited += poll
    yield {"type": "timeout"}


@router.get("/cases/{case_id}/stream")
async def case_stream(case_id: str, user: Principal = Depends(stream_user)):
    """Server-Sent Events fallback for environments that block WebSockets."""
    def check():
        with repo_scope() as db:
            get_case(db, user, case_id)
    await asyncio.to_thread(check)

    async def gen():
        async for msg in _event_stream(case_id):
            yield f"data: {json.dumps(msg)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.websocket("/ws/cases/{case_id}")
async def case_ws(websocket: WebSocket, case_id: str):
    try:
        user = principal_from_token(websocket.query_params.get("token", ""))

        def check():
            with repo_scope() as db:
                get_case(db, user, case_id)
        await asyncio.to_thread(check)
    except HTTPException:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        async for msg in _event_stream(case_id):
            await websocket.send_json(msg)
        await websocket.close()
    except WebSocketDisconnect:
        return
