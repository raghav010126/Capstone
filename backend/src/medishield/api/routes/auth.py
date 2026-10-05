from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from medishield.api.deps import get_db
from medishield.api.schemas import LoginRequest, TokenResponse, UserOut
from medishield.api.security import (
    PERMISSIONS,
    Principal,
    Role,
    client_key,
    create_token,
    current_user,
    limiter,
    require,
    verify_password,
)
from medishield.config import get_settings
from medishield.db import audit
from medishield.db.models import User

router = APIRouter(tags=["auth"])
_DUMMY_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO3mOtWqYQmOzO3q2wQe0r0rQ3pEw7pYa"      # equalises timing for unknown users


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    limiter.check(f"login:{client_key(request)}:{body.username}", get_settings().login_rate_per_min)
    user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not (user and user.active and ok):
        audit.append(db, body.username[:64], "login_failed", None, {"ip": client_key(request)})
        db.commit()
        raise HTTPException(401, "invalid username or password")
    audit.append(db, user.username, "login", None, {"role": user.role})
    return TokenResponse(access_token=create_token(user.username, Role(user.role)), username=user.username,
                         role=user.role, display_name=user.display_name)


@router.get("/auth/me", response_model=UserOut)
def me(user: Principal = Depends(current_user)):
    return UserOut(username=user.username, display_name=user.display_name, role=user.role.value,
                   permissions=sorted(p for p, roles in PERMISSIONS.items() if user.role in roles))


@router.get("/users", response_model=list[UserOut])
def users(_: Principal = Depends(require("user:admin")), db: Session = Depends(get_db)):
    return [UserOut(username=u.username, display_name=u.display_name, role=u.role)
            for u in db.execute(select(User).order_by(User.id)).scalars()]
