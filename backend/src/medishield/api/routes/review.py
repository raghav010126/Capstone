from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from medishield.api import schemas as S
from medishield.api.deps import get_case, get_db
from medishield.api.routes.cases import override_out, summary
from medishield.api.security import Principal, require
from medishield.config import get_settings
from medishield.db.models import Case, Override
from medishield.services import review as rv
from medishield.worker.queue import enqueue_case

router = APIRouter(tags=["review"])


@router.get("/review/reason-codes")
def reason_codes(_: Principal = Depends(require("review:queue"))):
    return {"reason_codes": rv.REASON_CODES, "four_eyes_amount": get_settings().four_eyes_amount}


@router.get("/review/queue", response_model=list[S.CaseSummary])
def review_queue(_: Principal = Depends(require("review:queue")), db: Session = Depends(get_db)):
    """Cases awaiting a human decision, most urgent first: SLA breached, then fraud risk, then oldest."""
    cases = db.execute(select(Case).where(Case.status == "IN_REVIEW")).scalars().all()
    pending = set(db.execute(select(Override.case_id).where(Override.status == "PENDING_APPROVAL")).scalars())
    rows = [summary(c, c.id in pending) for c in cases]
    rows.sort(key=lambda r: (not r.sla_breached, -r.risk_score, r.created_at))
    return rows


@router.post("/cases/{case_id}/override", response_model=S.OverrideOut, status_code=201)
def override(case_id: str, body: S.OverrideRequest, user: Principal = Depends(require("review:override")),
             db: Session = Depends(get_db)):
    case = get_case(db, user, case_id)
    ov = rv.request_override(db, user, case, body.decision, body.reason_code, body.note)
    return override_out(ov)


@router.get("/cases/{case_id}/overrides", response_model=list[S.OverrideOut])
def list_overrides(case_id: str, user: Principal = Depends(require("review:queue")), db: Session = Depends(get_db)):
    get_case(db, user, case_id)
    rows = db.execute(select(Override).where(Override.case_id == case_id).order_by(Override.id)).scalars()
    return [override_out(o) for o in rows]


def _override(db: Session, case_id: str, oid: int) -> Override:
    ov = db.get(Override, oid)
    if ov is None or ov.case_id != case_id:
        raise HTTPException(404, "override not found")
    return ov


@router.post("/cases/{case_id}/overrides/{override_id}/approve", response_model=S.OverrideOut)
def approve(case_id: str, override_id: int, user: Principal = Depends(require("review:approve")),
            db: Session = Depends(get_db)):
    case = get_case(db, user, case_id)
    return override_out(rv.approve_override(db, user, case, _override(db, case_id, override_id)))


@router.post("/cases/{case_id}/overrides/{override_id}/reject", response_model=S.OverrideOut)
def reject(case_id: str, override_id: int, body: S.DecisionNote, user: Principal = Depends(require("review:approve")),
           db: Session = Depends(get_db)):
    case = get_case(db, user, case_id)
    return override_out(rv.reject_override(db, user, case, _override(db, case_id, override_id), body.note))


@router.post("/cases/{case_id}/documents/{doc_id}/reclassify", response_model=S.CaseSummary, status_code=202)
def reclassify(case_id: str, doc_id: str, body: S.ReclassifyRequest,
               user: Principal = Depends(require("review:reclassify")), db: Session = Depends(get_db)):
    case = get_case(db, user, case_id)
    rv.reclassify(db, user, case, doc_id, body.doc_type, body.reason_code, body.note)
    db.commit()
    enqueue_case(case.id)
    return summary(case)
