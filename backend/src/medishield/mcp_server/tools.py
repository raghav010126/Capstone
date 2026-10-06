"""The MediShield MCP server: its tools, and who is calling them.

Every tool resolves the caller from the verified MediShield token (never from tool arguments), then enforces access with the
REST API's own functions: ``api.security.require`` for permissions, ``api.deps.get_case`` for case visibility (submitters only
see their own cases; any other id is "not found or not visible", whether or not it exists), and the route functions for
listing. ``ask_assistant`` goes through ``POST /chat``'s handler, so the assistant's refusals, rate limit and citations apply.
Each call writes an ``mcp_tool_called`` audit event with the tool name and case id only.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextvars import ContextVar
from typing import Annotated, Any, Literal, TypeVar

import anyio.to_thread
from fastapi import HTTPException
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from medishield.api.security import Principal, Role, require
from medishield.db import audit
from medishield.db.repo import Repo, repo_scope

T = TypeVar("T")
INSTRUCTIONS = """MediShield claims intake. Tools answer as the signed-in user and only return what that user's role may see
(submitters: policy coverage and their own cases; reviewers, auditors and admins: any case and the review queue). Coverage
answers come from the plan's exclusion table and cite the clause and page. Nothing here can approve, override or change a
case; that is done in the MediShield app."""


def _build_server() -> MCPServer:
    """MCPServer() calls logging.basicConfig, which would give an unconfigured root logger a handler without the app's PHI
    filter. The app owns logging: a placeholder handler during construction makes that call a no-op."""
    root = logging.getLogger()
    placeholder = None if root.handlers else logging.NullHandler()
    if placeholder:
        root.addHandler(placeholder)
    try:
        return MCPServer("medishield", title="MediShield", instructions=INSTRUCTIONS, version="0.3.0")
    finally:
        if placeholder:
            root.removeHandler(placeholder)


server = _build_server()
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

# The caller of the current tool call: set per HTTP request by medishield.mcp_server.http after the token is verified.
current_principal: ContextVar[Principal | None] = ContextVar("mcp_principal", default=None)
# stdio has no per-request token: python -m medishield.mcp_server installs a callable that re-verifies its token per call.
stdio_principal: Callable[[], Principal] | None = None


def caller() -> Principal:
    p = current_principal.get()
    if p is not None:
        return p
    if stdio_principal is not None:
        try:
            return stdio_principal()
        except HTTPException as e:
            raise ToolError(f"authentication failed: {e.detail}") from None
    raise ToolError("authentication required: send Authorization: Bearer <MediShield token>")


def _message(e: HTTPException, case_id: str | None) -> str:
    if e.status_code == 404 and case_id:
        return f"case {case_id} not found or not visible to you"          # one answer whether or not the case exists
    if e.status_code == 403:
        return f"permission denied: {e.detail}"
    if e.status_code == 401:
        return f"authentication failed: {e.detail}"
    return str(e.detail)


def _begin(tool: str, case_id: str | None) -> Principal:
    """Resolve the caller and write the audit event (committed on its own, so denied calls are recorded too)."""
    user = caller()
    with repo_scope() as db:
        audit.append(db, user.username, "mcp_tool_called", case_id, {"tool": tool})
    return user


def _run(tool: str, case_id: str | None, fn: Callable[[Principal, Repo], T]) -> T:
    user = _begin(tool, case_id)
    try:
        with repo_scope() as db:
            return fn(user, db)
    except HTTPException as e:
        raise ToolError(_message(e, case_id)) from None


def _summary(s) -> dict[str, Any]:
    return s.model_dump(mode="json")


# ── tools ────────────────────────────────────────────────────────────────────────────────────────────
@server.tool(annotations=READ_ONLY)
def check_coverage(cpt_code: Annotated[str, Field(description="5-character procedure code, e.g. 17000 or 0042T")],
                   plan: Annotated[str, Field(description="plan name, e.g. gold or silver")]) -> dict[str, Any]:
    """Is a procedure code covered on a plan? A deterministic answer from the plan's exclusion table (table 4.1) with the
    clause and page, plus the plan's in-network cost sharing for that kind of service. Needs policy:ask (every role)."""
    from medishield.mcp_server import coverage

    def go(user: Principal, _db: Repo) -> dict[str, Any]:
        require("policy:ask")(user)
        try:
            return coverage.check(coverage.policy_store(), cpt_code, plan)
        except coverage.CoverageInputError as e:
            raise ToolError(str(e)) from None
    return _run("check_coverage", None, go)


@server.tool(annotations=READ_ONLY)
def get_case(case_id: Annotated[str, Field(description="case id, e.g. CASE-1A2B3C4D", pattern=r"^CASE-[0-9A-Fa-f]{8}$")]) -> dict[str, Any]:
    """One case: status, automated and final decision, confidence, amount, justification, and each document's decision with
    the rule and reasons. Submitters only see their own cases."""
    from medishield.api.deps import get_case as visible_case
    from medishield.api.routes.cases import summary

    def go(user: Principal, db: Repo) -> dict[str, Any]:
        require("case:read")(user)
        c = visible_case(db, user, case_id)
        dec = c.decision or {}
        pending = any(o.status == "PENDING_APPROVAL" for o in db.list_overrides(c.id))      # as GET /cases/{id}
        return {**_summary(summary(c, pending)), "justification": dec.get("justification"),
                "documents": [{"doc_id": d.get("doc_id"), "doc_type": d.get("doc_type"), "decision": d.get("decision"),
                               "confidence": d.get("confidence"), "rule_id": d.get("rule_id"), "reasons": d.get("reasons", [])}
                              for d in dec.get("documents", [])],
                "url": f"/cases/view?id={c.id}"}
    return _run("get_case", case_id, go)


@server.tool(annotations=READ_ONLY)
def list_cases(status: Annotated[Literal["RECEIVED", "PROCESSING", "DECIDED", "IN_REVIEW", "FINALIZED", "FAILED"] | None, Field(
                   description="only cases with this status")] = None,
               limit: Annotated[int, Field(ge=1, le=200, description="at most this many, newest first")] = 20) -> dict[str, Any]:
    """Recent cases, newest first, like GET /cases. Submitters only get their own cases."""
    from medishield.api.routes import cases

    def go(user: Principal, db: Repo) -> dict[str, Any]:
        require("case:read")(user)
        rows = cases.list_cases(status=status, decision=None, limit=limit, offset=0, user=user, db=db)
        return {"cases": [_summary(r) for r in rows], "count": len(rows)}
    return _run("list_cases", None, go)


@server.tool(annotations=READ_ONLY)
def review_queue() -> dict[str, Any]:
    """Cases waiting for a human decision, most urgent first (SLA breached, then fraud risk, then oldest). Needs review:queue
    (reviewers, senior reviewers, auditors, admins)."""
    from medishield.api.routes import review

    def go(user: Principal, db: Repo) -> dict[str, Any]:
        require("review:queue")(user)
        rows = review.review_queue(user, db)
        return {"cases": [_summary(r) for r in rows], "count": len(rows)}
    return _run("review_queue", None, go)


@server.tool(annotations=READ_ONLY)
def case_status(case_id: Annotated[str, Field(description="case id, e.g. CASE-1A2B3C4D", pattern=r"^CASE-[0-9A-Fa-f]{8}$")]) -> dict[str, Any]:
    """Only the status of a case (one cheap read; use it to poll a case that is still processing)."""
    def go(user: Principal, db: Repo) -> dict[str, Any]:
        require("case:read")(user)
        head = db.case_header(case_id)                    # the read behind GET /cases/{id}/progress, with its visibility rule
        if head is None or (user.role == Role.SUBMITTER and head.submitted_by != user.username):
            raise HTTPException(404, "case not found")
        return {"case_id": head.id, "status": head.status}
    return _run("case_status", case_id, go)


@server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, idempotent_hint=False))
async def ask_assistant(question: Annotated[str, Field(min_length=1, max_length=2000, description="question in plain English")],
                        conversation_id: Annotated[str | None, Field(
                            description="pass back the conversation_id of an earlier answer for follow-up questions")] = None,
                        ) -> dict[str, Any]:
    """Ask MediShield's role-aware assistant (policies, cases, review queue, audit, operations: whatever your role may see).
    Answers carry [n] citations; questions outside your role are refused and audited."""
    from medishield.api import schemas as S
    from medishield.api.routes import chat

    user = await anyio.to_thread.run_sync(_begin, "ask_assistant", None)
    try:
        body = S.ChatRequest(question=question, conversation_id=conversation_id)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
        raise ToolError(f"invalid arguments: {problems}") from None
    try:
        out = await chat.chat(body, user)                 # POST /chat's handler: rate limit, payload, local or AgentCore
    except HTTPException as e:
        raise ToolError(_message(e, None)) from None
    return {"answer": out.get("answer"), "blocked": out.get("blocked", False), "route": out.get("route"), "role": out.get("role"),
            "conversation_id": out.get("conversation_id"), "sql": out.get("sql"), "sources": out.get("sources", [])}
