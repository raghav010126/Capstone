"""Hash-chained, tamper-evident audit log: ``hash = sha256(prev_hash + canonical(event))``.

The chain logic lives here; the storage (and the serialisation of concurrent appends) lives in the repo, so the same
verification runs on SQL and on DynamoDB. ``verify_chain`` recomputes every link, so editing, deleting or re-ordering any past
row is detected and located.
"""

from __future__ import annotations

import hashlib
import json

from medishield.db.repo import Repo

GENESIS = "0" * 64


def canonical(ts: str, actor: str, action: str, case_id: str | None, detail: dict) -> str:
    return json.dumps({"ts": ts, "actor": actor, "action": action, "case_id": case_id, "detail": detail},
                      sort_keys=True, separators=(",", ":"), default=str)


def chain_hash(prev_hash: str, body: str) -> str:
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def append(repo: Repo, actor: str, action: str, case_id: str | None = None, detail: dict | None = None):
    detail = json.loads(json.dumps(detail or {}, default=str))        # JSON-normalise before hashing
    return repo.append_audit(actor, action, case_id, detail)


def verify_chain(repo: Repo) -> dict:
    """Walk the whole chain. Returns {ok, length, broken_at, reason}."""
    prev, n = GENESIS, 0
    for ev in repo.iter_audit():
        n += 1
        if ev.prev_hash != prev:
            return {"ok": False, "length": n, "broken_at": ev.seq, "reason": "prev_hash does not link to the previous event"}
        if ev.hash != chain_hash(prev, canonical(ev.ts, ev.actor, ev.action, ev.case_id, ev.detail)):
            return {"ok": False, "length": n, "broken_at": ev.seq, "reason": "event content does not match its hash"}
        prev = ev.hash
    return {"ok": True, "length": n, "broken_at": None, "reason": None, "head": prev}
