"""Local MCP server over stdio, for Claude Desktop: ``python -m medishield.mcp_server``.

It runs the same tools in-process against the local MediShield state (database, policies, assistant), as the user of a
MediShield token, which is verified exactly as the API verifies it (signature, expiry, user still active) on every tool call:

* ``MEDISHIELD_TOKEN``: a token from ``POST /auth/login``; or
* ``MEDISHIELD_USER`` + ``MEDISHIELD_PASSWORD``: signs in at ``MEDISHIELD_API_URL`` (default http://localhost:8100) and signs in
  again when the token expires.

The token must come from an API that shares this machine's ``JWT_SECRET`` and database (the local ``make api``). For the AWS
deployment, connect to ``https://<site>/api/mcp`` over HTTP instead (docs/mcp.md).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import urllib.error
import urllib.request

from fastapi import HTTPException

from medishield.api.security import Principal, install_log_redaction, principal_from_token

DEFAULT_API_URL = "http://localhost:8100"


def login(api_url: str, username: str, password: str) -> str:
    req = urllib.request.Request(f"{api_url.rstrip('/')}/auth/login", method="POST",
                                 data=json.dumps({"username": username, "password": password}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())["access_token"]
    except urllib.error.HTTPError as e:
        raise HTTPException(401, f"sign-in at {api_url} failed (HTTP {e.code})") from None
    except (urllib.error.URLError, OSError) as e:
        raise HTTPException(401, f"cannot reach {api_url} to sign in: {e}") from None


class StdioAuth:
    """The stdio caller. Re-verified per call, so an expired token or a disabled user stops working mid-session."""

    def __init__(self, token: str | None = None, username: str | None = None, password: str | None = None,
                 api_url: str = DEFAULT_API_URL):
        if not token and not (username and password):
            raise HTTPException(401, "set MEDISHIELD_TOKEN, or MEDISHIELD_USER and MEDISHIELD_PASSWORD")
        self.token, self.username, self.password, self.api_url = token or None, username, password, api_url
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> StdioAuth:
        e = os.environ
        return cls(e.get("MEDISHIELD_TOKEN"), e.get("MEDISHIELD_USER"), e.get("MEDISHIELD_PASSWORD"),
                   e.get("MEDISHIELD_API_URL") or DEFAULT_API_URL)

    def __call__(self) -> Principal:
        with self._lock:
            if self.token is None:
                self.token = login(self.api_url, self.username or "", self.password or "")
            try:
                return principal_from_token(self.token)
            except HTTPException:
                if not (self.username and self.password):        # a fixed token cannot be renewed
                    raise
            self.token = login(self.api_url, self.username, self.password)
            return principal_from_token(self.token)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)       # stdout carries the protocol
    install_log_redaction()
    try:
        auth = StdioAuth.from_env()
        who = auth()
    except HTTPException as e:
        sys.exit(f"medishield MCP: {e.detail}")
    from medishield.mcp_server import tools

    tools.stdio_principal = auth
    print(f"medishield MCP: serving over stdio as {who.username} ({who.role.value})", file=sys.stderr)
    tools.server.run("stdio")


if __name__ == "__main__":
    main()
