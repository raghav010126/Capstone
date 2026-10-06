"""AWS Lambda entry points.

``api_handler``     the FastAPI application behind a Lambda Function URL (CloudFront forwards ``/api/*`` to it).
``worker_handler``  an SQS-triggered function that runs the case graph (or ingests a policy) for each message.

Both run with ``MEDISHIELD_DB=dynamodb``, ``STORAGE_BACKEND=s3`` and ``MEDISHIELD_QUEUE=sqs``. Secrets come from SSM Parameter
Store at cold start (``load_secrets``), so they are never in the function configuration or the template.
"""

from __future__ import annotations

import json
import logging
import os
import threading

log = logging.getLogger(__name__)
_init_lock = threading.Lock()
_ready = False


def load_secrets() -> None:
    """Copy SSM parameters under ``$SSM_PREFIX`` (e.g. /medishield/) into the environment as upper-case variable names."""
    prefix = os.environ.get("SSM_PREFIX", "")
    if not prefix:
        return
    import boto3

    ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    for page in ssm.get_paginator("get_parameters_by_path").paginate(Path=prefix, WithDecryption=True):
        for p in page["Parameters"]:
            os.environ.setdefault(p["Name"].rsplit("/", 1)[-1].upper(), p["Value"])


def link_baked_caches() -> None:
    """The image carries read-only model files (embedding models, policy index); the process cache dir must be writable, so it lives
    in /tmp and the baked folders are linked into it."""
    baked, cache = os.environ.get("BAKED_CACHE"), os.environ.get("MEDISHIELD_CACHE")
    if not baked or not cache:
        return
    os.makedirs(cache, exist_ok=True)
    for name in os.listdir(baked):
        dst = os.path.join(cache, name)
        if not os.path.lexists(dst):
            os.symlink(os.path.join(baked, name), dst)


def _init() -> None:
    global _ready
    with _init_lock:
        if _ready:
            return
        link_baked_caches()
        load_secrets()
        from medishield.config import get_settings

        get_settings.cache_clear()
        _ready = True


_api = None


def api_handler(event, context):
    global _api
    _init()
    if _api is None:
        from mangum import Mangum

        from medishield.api.main import create_app, seed_users
        from medishield.config import get_settings

        seed_users()                                      # idempotent conditional writes
        _api = Mangum(create_app(), lifespan="off", api_gateway_base_path=get_settings().api_base_path or "/")
    return _api(event, context)


def worker_handler(event, context):
    """SQS batch (size 1). A failure inside the pipeline is recorded on the case itself, so the message is not retried."""
    _init()
    from medishield.records import get_records
    from medishield.services import cases, policies

    records = get_records()
    for rec in event.get("Records", []):
        msg = json.loads(rec["body"])
        if msg["task"] == "process_case":
            records.reset_processed()
            cases.rebuild_registry()                      # duplicate detection needs every earlier decided claim
            cases.process_case(msg["arg"])
        elif msg["task"] == "ingest_policy":
            policies.ingest_policy(int(msg["arg"]))
        else:
            log.error("unknown task %r", msg["task"])
    return {"ok": True}
