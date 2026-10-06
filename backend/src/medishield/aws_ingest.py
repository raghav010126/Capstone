"""Policy ingestion Lambda (AWS). Docling and PyTorch do not fit the 2 GB AgentCore image, so uploaded policy PDFs are parsed
here, in a separate image (``infra/Dockerfile.ingest``) with Docling's models baked in.

The API stores the PDF in S3, records the policy as INGESTING and invokes this function asynchronously with ``{"policy_id": n}``.
The handler runs the same ingestion as a local worker (``services.policies.ingest_policy``): it downloads the PDF, parses it,
publishes the index JSON to ``policies/index/`` and marks the policy READY, or FAILED with a short error. New agent sessions then
load that index from S3 and never need Docling.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)
logging.getLogger("medishield").setLevel(logging.INFO)       # CloudWatch shows how long the parse took


def handler(event, context=None) -> dict:
    from medishield.db.repo import repo_scope
    from medishield.services import policies

    policy_id = int(event["policy_id"])
    with repo_scope() as db:
        p = db.get_policy(policy_id)
        status = p.status if p else None
    if status != "INGESTING":                                 # unknown id, or a repeated delivery of a finished job
        log.warning("policy %s is %s: nothing to do", policy_id, status)
        return {"policy_id": policy_id, "status": status, "skipped": True}
    policies.ingest_policy(policy_id)                         # records READY or FAILED itself
    with repo_scope() as db:
        return {"policy_id": policy_id, "status": db.get_policy(policy_id).status}
