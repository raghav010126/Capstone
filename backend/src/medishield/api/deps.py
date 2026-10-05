from __future__ import annotations

from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from medishield.api.security import Principal, Role, _bearer, principal_from_token
from medishield.db.models import Case
from medishield.db.session import get_engine, session_scope  # noqa: F401


def get_db():
    with session_scope() as db:
        yield db


def get_case(db: Session, user: Principal, case_id: str) -> Case:
    """Load a case the caller may see. Submitters only see their own; others get 404, not 403, so case ids
    can't be probed."""
    case = db.get(Case, case_id)
    if case is None or (user.role == Role.SUBMITTER and case.submitted_by != user.username):
        raise HTTPException(404, "case not found")
    return case


def stream_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                token: str | None = Query(default=None)) -> Principal:
    """Header or ``?token=`` (EventSource / WebSocket cannot set Authorization headers)."""
    raw = creds.credentials if creds else token
    if not raw:
        raise HTTPException(401, "authentication required")
    return principal_from_token(raw)
