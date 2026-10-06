"""Policy upload -> Docling ingestion -> structured exclusion rules ("policy as data").

Uploading a new policy PDF replaces the plan's chunks and its table-4.1 rules; the vector store is rebuilt so
the next claim is judged against the new policy with no code change. On AWS the PDF and its parsed index live in S3
(``policy_s3``) and a separate Lambda does the parsing.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import replace
from pathlib import Path

from medishield.config import get_settings
from medishield.db import audit
from medishield.db.repo import repo_scope
from medishield.services import policy_s3

log = logging.getLogger(__name__)


def policy_path(policy) -> Path:
    return _pdf_path(policy.plan, policy.sha256)


def _pdf_path(plan: str, sha256: str) -> Path:
    return get_settings().policy_upload_dir / f"{plan}-{sha256[:12]}.pdf"


def save_upload(plan: str, filename: str, data: bytes, uploader: str) -> int:
    """Validate and register an uploaded policy PDF; returns the policy id (ingestion is queued separately)."""
    from medishield.api.uploads import UploadError

    if not data.startswith(b"%PDF-"):
        raise UploadError("not a PDF", 415)
    digest = hashlib.sha256(data).hexdigest()
    path = _pdf_path(plan, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if policy_s3.enabled():                        # AWS: the ingest Lambda and the agent runtimes read it from S3
        policy_s3.put_pdf(path, data)
    with repo_scope() as db:
        p = db.add_policy(plan, filename, digest, uploader)
        audit.append(db, uploader, "policy_uploaded", None, {"plan": plan, "sha256": digest[:16], "filename": filename})
        return p.id


def ingest_policy(policy_id: int) -> None:
    from medishield.rag import (  # loaded here: the API only needs them when a policy is ingested
        ingest,
        retrieve,
    )

    with repo_scope() as db:
        p = db.get_policy(policy_id)
        path, plan = policy_path(p), p.plan
    try:
        if policy_s3.enabled():
            policy_s3.download_pdf(path)           # this worker may not be the process that received the upload
        idx = ingest.load_or_ingest(path)
        idx.plan = plan
        for c in idx.chunks:
            c.plan = plan
        idx.ranges = [replace(r, plan=plan) for r in idx.ranges]
        if policy_s3.enabled():
            policy_s3.publish_index(path)          # before READY: a runtime that sees READY always finds the index
        retrieve.get_store.cache_clear()           # next claim rebuilds the store with the new policy
        with repo_scope() as db:
            p = db.get_policy(policy_id)
            p.status, p.product_code, p.chunk_count = "READY", idx.product_code, len(idx.chunks)
            p.ranges = [r.to_dict() for r in idx.ranges]
            db.save_policy(p)
            audit.append(db, "system", "policy_ingested", None,
                         {"plan": plan, "chunks": len(idx.chunks), "exclusion_rows": len(idx.ranges)})
    except Exception as e:
        log.exception("policy ingestion failed")
        mark_failed(policy_id, f"{type(e).__name__}: {str(e)[:300]}")


def mark_failed(policy_id: int, error: str) -> None:
    with repo_scope() as db:
        p = db.get_policy(policy_id)
        p.status, p.error = "FAILED", error
        db.save_policy(p)


def uploaded_policy_paths() -> list[Path]:
    """READY uploads, newest per plan (an upload supersedes the bundled policy for the same plan).

    On AWS their PDFs and parsed indexes are fetched from S3 first. If they are missing there, the plan's previous upload (or the
    bundled policy) applies: the PDF is never parsed here."""
    with repo_scope() as db:
        ready = [(p.plan, policy_path(p)) for p in db.ready_policies()]          # oldest first
    remote, chosen = policy_s3.enabled(), {}
    for plan, path in reversed(ready):
        if plan not in chosen and (not remote or policy_s3.fetch(path)):
            chosen[plan] = path
    return [chosen[plan] for plan in dict.fromkeys(plan for plan, _ in ready) if plan in chosen]


__all__ = ["ingest_policy", "mark_failed", "policy_path", "save_upload", "uploaded_policy_paths"]
