"""JWT authentication, role-based access control, rate limiting, and PHI redaction for logs."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from medishield.config import get_settings
from medishield.db.models import User
from medishield.db.session import session_scope

ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)


class Role(StrEnum):
    SUBMITTER = "submitter"                # uploads and sees their own cases
    REVIEWER = "reviewer"                  # works the review queue; overrides up to the four-eyes amount
    SENIOR_REVIEWER = "senior_reviewer"    # approves high-value overrides (second pair of eyes)
    AUDITOR = "auditor"                    # read-only: cases, audit log, reports
    ADMIN = "admin"                        # policies, users, everything


R = Role
PERMISSIONS: dict[str, set[Role]] = {
    "case:create": {R.SUBMITTER, R.REVIEWER, R.SENIOR_REVIEWER, R.ADMIN},
    "case:read": set(Role),                              # submitters are further limited to their own cases
    "case:read_all": {R.REVIEWER, R.SENIOR_REVIEWER, R.AUDITOR, R.ADMIN},
    "review:queue": {R.REVIEWER, R.SENIOR_REVIEWER, R.AUDITOR, R.ADMIN},
    "review:override": {R.REVIEWER, R.SENIOR_REVIEWER, R.ADMIN},
    "review:approve": {R.SENIOR_REVIEWER, R.ADMIN},
    "review:reclassify": {R.REVIEWER, R.SENIOR_REVIEWER, R.ADMIN},
    "audit:read": {R.AUDITOR, R.SENIOR_REVIEWER, R.ADMIN},
    "report:download": {R.REVIEWER, R.SENIOR_REVIEWER, R.AUDITOR, R.ADMIN},
    "policy:read": {R.REVIEWER, R.SENIOR_REVIEWER, R.AUDITOR, R.ADMIN},
    "policy:upload": {R.ADMIN},
    "user:admin": {R.ADMIN},
    "ops:read": {R.REVIEWER, R.SENIOR_REVIEWER, R.AUDITOR, R.ADMIN},
}


@dataclass(frozen=True)
class Principal:
    username: str
    role: Role
    display_name: str

    def can(self, permission: str) -> bool:
        return self.role in PERMISSIONS[permission]


# ── passwords & tokens ───────────────────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(int(os.environ.get("BCRYPT_ROUNDS", "12")))).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(username: str, role: Role) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    return jwt.encode({"sub": username, "role": role.value, "iat": now,
                       "exp": now + timedelta(minutes=s.jwt_ttl_minutes)}, s.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token") from e


def principal_from_token(token: str) -> Principal:
    claims = decode_token(token)
    with session_scope() as db:                           # the user must still exist and be active
        u = db.execute(select(User).where(User.username == claims["sub"])).scalar_one_or_none()
        if u is None or not u.active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown or disabled user")
        return Principal(u.username, Role(u.role), u.display_name)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    return principal_from_token(creds.credentials)


def require(permission: str):
    """Dependency factory: ``user = Depends(require("review:override"))``."""
    def dep(user: Principal = Depends(current_user)) -> Principal:
        if not user.can(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"role '{user.role.value}' lacks permission '{permission}'")
        return user
    return dep


def ws_user(websocket: WebSocket) -> Principal:
    token = websocket.query_params.get("token", "")
    return principal_from_token(token)


# ── rate limiting (sliding window, in-process) ───────────────────────────────────────────────────────
class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float = 60.0) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded; retry shortly",
                                    headers={"Retry-After": str(int(window - (now - q[0])) + 1)})
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_key(request: Request, user: str | None = None) -> str:
    return user or (request.client.host if request.client else "unknown")


# ── PHI redaction for logs and traces ────────────────────────────────────────────────────────────────
_PHI_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b\d{2}/\d{2}/\d{4}\b"), "[DATE]"),
    (re.compile(r"\bMED-[A-Z]{3}-\d{5,}\b"), "[POLICY]"),
    (re.compile(r"\bNPI-?\d{10}\b"), "[NPI]"),
    (re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+ [A-Z]\.(?!\w)"), "[NAME]"),
    (re.compile(r"(?i)bearer\s+[\w.-]+"), "Bearer [TOKEN]"),
    (re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+"), "[JWT]"),               # any JWT, wherever it appears
    (re.compile(r"(?i)([?&]token=)[^&\s\"]+"), r"\1[TOKEN]"),            # WebSocket / SSE URLs carry the login token
]


def redact(text: str) -> str:
    for pat, repl in _PHI_PATTERNS:
        text = pat.sub(repl, text)
    return text


class PHIFilter(logging.Filter):
    """Redact in place and keep ``record.args`` intact: formatters (uvicorn's access log unpacks five fixed
    arguments) depend on its shape."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
        return True


def install_log_redaction() -> None:
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "medishield"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, PHIFilter) for f in lg.filters):
            lg.addFilter(PHIFilter())
            for h in lg.handlers:
                h.addFilter(PHIFilter())
