"""Policy upload -> Docling ingestion -> structured exclusion rules ("policy as data").

Uploading a new policy PDF replaces the plan's chunks and its table-4.1 rules; the vector store is rebuilt so
the next claim is judged against the new policy with no code change.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import replace
from pathlib import Path

from medishield.config import get_settings
from medishield.db import audit
from medishield.db.repo import repo_scope
from medishield.rag import ingest, retrieve

log = logging.getLogger(__name__)


def policy_path(policy) -> Path:
    return get_settings().policy_upload_dir / f"{policy.plan}-{policy.sha256[:12]}.pdf"


def save_upload(plan: str, filename: str, data: bytes, uploader: str) -> int:
    """Validate and register an uploaded policy PDF; returns the policy id (ingestion is queued separately)."""
    from medishield.api.uploads import UploadError

    if not data.startswith(b"%PDF-"):
        raise UploadError("not a PDF", 415)
    digest = hashlib.sha256(data).hexdigest()
    with repo_scope() as db:
        p = db.add_policy(plan, filename, digest, uploader)
        path = policy_path(p)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        audit.append(db, uploader, "policy_uploaded", None, {"plan": plan, "sha256": digest[:16], "filename": filename})
        return p.id


def ingest_policy(policy_id: int) -> None:
    with repo_scope() as db:
        p = db.get_policy(policy_id)
        path, plan = policy_path(p), p.plan
    try:
        idx = ingest.load_or_ingest(path)
        idx.plan = plan
        for c in idx.chunks:
            c.plan = plan
        idx.ranges = [replace(r, plan=plan) for r in idx.ranges]
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
        with repo_scope() as db:
            p = db.get_policy(policy_id)
            p.status, p.error = "FAILED", f"{type(e).__name__}: {str(e)[:300]}"
            db.save_policy(p)


def uploaded_policy_paths() -> list[Path]:
    """READY uploads, newest per plan (an upload supersedes the bundled policy for the same plan)."""
    with repo_scope() as db:
        latest = {p.plan: policy_path(p) for p in db.ready_policies()}
    return list(latest.values())


__all__ = ["ingest_policy", "policy_path", "save_upload", "uploaded_policy_paths"]
