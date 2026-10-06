"""API Lambda entry point. Everything is loaded during Lambda's init phase (before any request waits), and a scheduled
``{"warm": true}`` ping keeps one instance ready so signing in is rarely a cold start (free-tier cost)."""

from __future__ import annotations

from medishield.aws_handlers import _init

_init()

from mangum import Mangum

from medishield.api.main import create_app, seed_users
from medishield.config import get_settings

seed_users()                                             # idempotent conditional writes
_app = Mangum(create_app(), lifespan="off", api_gateway_base_path=get_settings().api_base_path or "/")


def handler(event, context):
    if isinstance(event, dict) and event.get("warm"):    # EventBridge keep-warm ping
        return {"warm": True}
    return _app(event, context)
