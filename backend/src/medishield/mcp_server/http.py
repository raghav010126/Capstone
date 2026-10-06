"""``/mcp`` on the API: MCP over Streamable HTTP, stateless, JSON responses (no SSE, no server-side session).

Behind CloudFront and Lambda (Mangum, ``lifespan="off"``) there is no long-running process to own the SDK's session manager, so
each POST gets its own stateless manager, entered and left within the request: one JSON-RPC message in, one JSON response out,
nothing kept between invocations. GET (the optional server-to-client SSE stream) and DELETE (session end) answer 405, as the
spec allows for a server without either; a GET stream would otherwise hold a Lambda open until its timeout.

The caller is the user of the ``Authorization: Bearer <MediShield JWT>`` header, verified exactly as the REST API does
(``api.security.principal_from_token``: signature, expiry, and the user still exists and is active). Missing or invalid
tokens get 401 before any MCP processing. The SDK is imported on the first MCP request, so the API's cold start does not pay
for it.
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.types import Receive, Scope, Send

from medishield.api.security import principal_from_token


async def _json(send: Send, status: int, body: dict, headers: dict[str, str] | None = None) -> None:
    raw = json.dumps(body).encode()
    hdrs = [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode()),
            *((k.lower().encode(), v.encode()) for k, v in (headers or {}).items())]
    await send({"type": "http.response.start", "status": status, "headers": hdrs})
    await send({"type": "http.response.body", "body": raw})


async def _unauthorized(send: Send, description: str) -> None:
    await _json(send, 401, {"error": "invalid_token", "error_description": description},
                {"WWW-Authenticate": f'Bearer error="invalid_token", error_description="{description}"'})


def _bearer(scope: Scope) -> str | None:
    for k, v in scope.get("headers") or []:
        if k == b"authorization":
            scheme, _, token = v.decode("latin-1").partition(" ")
            return token.strip() if scheme.lower() == "bearer" and token.strip() else None
    return None


class MCPEndpoint:
    """ASGI app for ``/mcp``."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["method"] != "POST":
            error = {"code": -32000, "message": "Method not allowed: this server is stateless; POST JSON-RPC messages"}
            await _json(send, 405, {"jsonrpc": "2.0", "id": None, "error": error}, {"Allow": "POST"})
            return
        token = _bearer(scope)
        if token is None:
            await _unauthorized(send, "authentication required: send Authorization: Bearer <MediShield token>")
            return
        try:
            user = await run_in_threadpool(principal_from_token, token)
        except HTTPException as e:
            await _unauthorized(send, str(e.detail))
            return

        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

        from medishield.mcp_server import tools

        # streamable_http_app() would build this same manager, but tie it to a Starlette lifespan that Lambda never runs
        manager = StreamableHTTPSessionManager(tools.server._lowlevel_server, json_response=True, stateless=True)
        mark = tools.current_principal.set(user)          # the per-request task group below inherits it
        try:
            async with manager.run():
                await manager.handle_request(scope, receive, send)
        finally:
            tools.current_principal.reset(mark)


endpoint = MCPEndpoint()
