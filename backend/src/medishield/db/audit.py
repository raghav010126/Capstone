"""Hash-chained, tamper-evident audit log: ``hash = sha256(prev_hash + canonical(event))``.

Appends are serialised (process lock + a transaction that reads the chain head), and ``verify_chain``
recomputes every link, so editing, deleting or re-ordering any past row is detected and located.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from medishield.db.models import AuditEvent

GENESIS = "0" * 64
_lock = threading.Lock()


def canonical(ts: str, actor: str, action: str, case_id: str | None, detail: dict) -> str:
    return json.dumps({"ts": ts, "actor": actor, "action": action, "case_id": case_id, "detail": detail},
                      sort_keys=True, separators=(",", ":"), default=str)


def chain_hash(prev_hash: str, body: str) -> str:
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def append(session: Session, actor: str, action: str, case_id: str | None = None,
           detail: dict | None = None) -> AuditEvent:
    detail = json.loads(json.dumps(detail or {}, default=str))        # JSON-normalise before hashing
    with _lock:
        head = session.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
        prev = head.hash if head else GENESIS
        ts = datetime.now(UTC).isoformat(timespec="microseconds")
        ev = AuditEvent(ts=ts, actor=actor, action=action, case_id=case_id, detail=detail, prev_hash=prev,
                        hash=chain_hash(prev, canonical(ts, actor, action, case_id, detail)))
        session.add(ev)
        session.flush()
    return ev


def verify_chain(session: Session) -> dict:
    """Walk the whole chain. Returns {ok, length, broken_at, reason}."""
    prev, n = GENESIS, 0
    for ev in session.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars():
        n += 1
        if ev.prev_hash != prev:
            return {"ok": False, "length": n, "broken_at": ev.seq, "reason": "prev_hash does not link to the previous event"}
        if ev.hash != chain_hash(prev, canonical(ev.ts, ev.actor, ev.action, ev.case_id, ev.detail)):
            return {"ok": False, "length": n, "broken_at": ev.seq, "reason": "event content does not match its hash"}
        prev = ev.hash
    return {"ok": True, "length": n, "broken_at": None, "reason": None, "head": prev}
