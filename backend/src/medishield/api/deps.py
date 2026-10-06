from __future__ import annotations

from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials

from medishield.api.security import Principal, Role, _bearer, principal_from_token
from medishield.db.repo import Repo, repo_scope


def get_db():
    """Request-scoped repo: commits when the request succeeds, rolls back on an error."""
    with repo_scope() as repo:
        yield repo


def get_case(db: Repo, user: Principal, case_id: str):
    """Load a case the caller may see. Submitters only see their own; others get 404, not 403, so case ids
    can't be probed."""
    case = db.get_case(case_id)
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
