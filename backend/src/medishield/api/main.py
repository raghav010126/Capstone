"""FastAPI application: ingestion API, case management, review workflow, audit, policies, live status."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from medishield.api.routes import audit, auth, cases, chat, ops, policies, review
from medishield.api.routes import intake as email_intake
from medishield.api.security import Role, hash_password, install_log_redaction
from medishield.config import get_settings
from medishield.db.repo import repo_scope
from medishield.db.session import get_engine
from medishield.mcp_server.http import endpoint as mcp_endpoint
from medishield.worker.queue import start_worker

log = logging.getLogger("medishield")
DEMO_USERS = [("submitter", "Sam Submitter", Role.SUBMITTER), ("reviewer", "Riley Reviewer", Role.REVIEWER),
              ("senior", "Sasha Senior Reviewer", Role.SENIOR_REVIEWER), ("auditor", "Alex Auditor", Role.AUDITOR),
              ("admin", "Ada Admin", Role.ADMIN)]
ready = {"policy_store": False, "registry_claims": 0}


def seed_users() -> None:
    import os

    s = get_settings()
    wanted = [(u, n, r, f"{u}-demo") for u, n, r in DEMO_USERS] if s.demo_users else []
    if os.environ.get("ADMIN_PASSWORD"):
        wanted.append((os.environ.get("ADMIN_USERNAME", "admin"), "Administrator", Role.ADMIN, os.environ["ADMIN_PASSWORD"]))
    with repo_scope() as db:
        for username, name, role, pw in wanted:
            if db.get_user(username) is None:
                db.add_user(username, name, role.value, hash_password(pw))


def _warm() -> None:
    from medishield.rag.retrieve import get_store
    from medishield.services.cases import rebuild_registry

    try:
        ready["registry_claims"] = rebuild_registry()
        get_store()
        ready["policy_store"] = True
    except Exception:
        log.exception("warm-up failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os

    install_log_redaction()
    get_engine()
    seed_users()
    worker = None
    if os.environ.get("MEDISHIELD_WORKER", "inline") == "inline" and not get_settings().queue_immediate:
        worker = start_worker()
    threading.Thread(target=_warm, daemon=True, name="warmup").start()
    yield
    if worker:
        worker.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="MediShield Document Intake API", version="0.3.0", lifespan=lifespan,
                  description="Multi-agent claims intake: upload, classify, extract, verify, check policy, "
                              "score fraud, decide - with human review, four-eyes approval and a tamper-evident audit log.")
    app.add_middleware(CORSMiddleware, allow_origins=list(get_settings().cors_origins), allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse({"detail": "internal error"}, status_code=500)   # never leak internals / PHI

    @app.get("/readyz", tags=["ops"])
    def readyz():
        return {"status": "ready" if ready["policy_store"] else "warming", **ready}

    for r in (auth.router, cases.router, review.router, audit.router, policies.router, ops.router, chat.router):
        app.include_router(r)
    app.include_router(email_intake.router)
    app.add_route("/mcp", mcp_endpoint, include_in_schema=False)   # MCP (Streamable HTTP, stateless JSON), docs/mcp.md
    return app


app = create_app()
