from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from medishield.api import schemas as S
from medishield.api.deps import get_case, get_db
from medishield.api.security import Principal, require
from medishield.db import audit
from medishield.db.repo import Repo
from medishield.reports.case_pdf import build_case_pdf

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=list[S.AuditOut])
def audit_log(case_id: str | None = None, action: str | None = None, limit: int = Query(100, le=500), offset: int = 0,
              _: Principal = Depends(require("audit:read")), db: Repo = Depends(get_db)):
    rows = db.list_audit(case_id=case_id, action=action, limit=limit, offset=offset)
    return [S.AuditOut.model_validate(e, from_attributes=True) for e in rows]


@router.get("/audit/verify", response_model=S.ChainStatus)
def verify(_: Principal = Depends(require("audit:read")), db: Repo = Depends(get_db)):
    return audit.verify_chain(db)


@router.get("/cases/{case_id}/report.pdf")
def report(case_id: str, user: Principal = Depends(require("report:download")), db: Repo = Depends(get_db)):
    case = get_case(db, user, case_id)
    pdf = build_case_pdf(case, db.list_overrides(case.id), db.audit_for_case(case.id), audit.verify_chain(db))
    audit.append(db, user.username, "report_downloaded", case.id, {"bytes": len(pdf)})
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{case.id}-report.pdf"'})
