from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from medishield.api import schemas as S
from medishield.api.deps import get_db
from medishield.api.security import Principal, require
from medishield.api.uploads import UploadError
from medishield.db.models import PolicyDoc
from medishield.services import policies as svc
from medishield.worker.queue import enqueue_policy

router = APIRouter(tags=["policies"])
MAX_POLICY_BYTES = 25 * 1024 * 1024


def out(p: PolicyDoc) -> S.PolicyOut:
    return S.PolicyOut(id=p.id, plan=p.plan, filename=p.filename, status=p.status, product_code=p.product_code,
                       chunk_count=p.chunk_count, exclusion_rows=len(p.ranges or []), uploaded_by=p.uploaded_by,
                       error=p.error, created_at=p.created_at)


@router.get("/policies", response_model=list[S.PolicyOut])
def list_policies(_: Principal = Depends(require("policy:read")), db: Session = Depends(get_db)):
    return [out(p) for p in db.execute(select(PolicyDoc).order_by(PolicyDoc.id.desc())).scalars()]


@router.get("/policies/{policy_id}", response_model=S.PolicyOut)
def policy_status(policy_id: int, _: Principal = Depends(require("policy:read")), db: Session = Depends(get_db)):
    p = db.get(PolicyDoc, policy_id)
    if p is None:
        raise HTTPException(404, "policy not found")
    return out(p)


@router.get("/policies/{policy_id}/ranges")
def policy_ranges(policy_id: int, _: Principal = Depends(require("policy:read")), db: Session = Depends(get_db)):
    p = db.get(PolicyDoc, policy_id)
    if p is None:
        raise HTTPException(404, "policy not found")
    return {"plan": p.plan, "ranges": p.ranges or []}


@router.post("/policies", response_model=S.PolicyOut, status_code=202)
async def upload_policy(plan: str = Form(..., pattern=r"^[a-z][a-z0-9_]{1,23}$"), file: UploadFile = File(...),
                        user: Principal = Depends(require("policy:upload")), db: Session = Depends(get_db)):
    data = await file.read(MAX_POLICY_BYTES + 1)
    if len(data) > MAX_POLICY_BYTES:
        raise HTTPException(413, "policy PDF exceeds 25 MB")
    try:
        pid = svc.save_upload(plan, re.sub(r"[^\w.\- ]", "_", file.filename or "policy.pdf"), data, user.username)
    except UploadError as e:
        raise HTTPException(e.status, str(e)) from e
    db.commit()
    enqueue_policy(pid)
    return out(db.get(PolicyDoc, pid))

