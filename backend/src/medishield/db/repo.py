"""Data access behind one small interface, so the same application runs on SQL (SQLite / Postgres) or on DynamoDB.

Every read and write the application performs goes through a ``Repo``. Records returned by a repo expose the same attributes
as the ORM models in ``db.models`` (``case.status``, ``case.documents``, ``ov.reason_code`` ...), so routes and services read
them identically whichever backend produced them. After changing a record, call the matching ``save_*`` (a no-op for SQL, where
the session tracks changes; a write for DynamoDB) and finally ``commit()``.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from medishield.db.models import (
    AgentRunRow,
    AuditEvent,
    Case,
    CaseEvent,
    Override,
    PolicyDoc,
    User,
    utcnow,
)


class Repo(ABC):
    """Everything the application needs from storage."""

    # ── transaction ──────────────────────────────────────────────────────────────────────────────────
    @abstractmethod
    def commit(self) -> None: ...

    # ── users ────────────────────────────────────────────────────────────────────────────────────────
    @abstractmethod
    def get_user(self, username: str) -> Any: ...
    @abstractmethod
    def list_users(self) -> list[Any]: ...
    @abstractmethod
    def add_user(self, username: str, display_name: str, role: str, password_hash: str) -> None: ...

    # ── cases and their documents ────────────────────────────────────────────────────────────────────
    @abstractmethod
    def get_case(self, case_id: str) -> Any: ...
    def case_header(self, case_id: str) -> Any:
        """Only the case's scalar fields (status, owner, ...): no documents or agent output. For status polling."""
        return self.get_case(case_id)

    @abstractmethod
    def find_case_by_idempotency(self, username: str, key: str) -> Any: ...
    @abstractmethod
    def add_case(self, case: Any) -> tuple[Any, bool]:
        """Insert a new case; returns (case, created). If the submitter's Idempotency-Key was already used the original case is
        returned with created=False."""
    @abstractmethod
    def save_case(self, case: Any) -> None: ...
    @abstractmethod
    def save_document(self, doc: Any) -> None: ...
    @abstractmethod
    def list_cases(self, *, submitted_by: str | None = None, status: str | None = None, decision: str | None = None,
                   limit: int = 50, offset: int = 0) -> list[Any]: ...
    @abstractmethod
    def all_cases(self) -> list[Any]: ...
    @abstractmethod
    def cases_by_status(self, status: str) -> list[Any]: ...
    def case_headers(self) -> list[Any]:
        """Every case's scalar fields (no documents; ``decision`` may be absent). For aggregate views."""
        return self.all_cases()

    def case_decisions(self, case_ids: Iterable[str]) -> dict[str, dict]:
        """The stored decision JSON (CaseDecision dump) of each listed case that has one, in as few reads as possible."""
        return {cid: c.decision for cid in case_ids if (c := self.get_case(cid)) is not None and c.decision}

    # ── agent runs ───────────────────────────────────────────────────────────────────────────────────
    @abstractmethod
    def replace_agent_runs(self, case_id: str, runs: list[dict]) -> None: ...
    @abstractmethod
    def list_agent_runs(self, case_id: str) -> list[Any]: ...

    # ── progress events ──────────────────────────────────────────────────────────────────────────────
    @abstractmethod
    def add_event(self, case_id: str, ev: dict) -> None: ...
    @abstractmethod
    def events_after(self, case_id: str, last_id: int) -> list[Any]: ...
    @abstractmethod
    def clear_events(self, case_id: str) -> None: ...

    # ── overrides ────────────────────────────────────────────────────────────────────────────────────
    @abstractmethod
    def add_override(self, ov: Any) -> Any: ...
    @abstractmethod
    def get_override(self, case_id: str, override_id: int) -> Any: ...
    @abstractmethod
    def list_overrides(self, case_id: str) -> list[Any]: ...
    @abstractmethod
    def save_override(self, ov: Any) -> None: ...
    @abstractmethod
    def pending_override(self, case_id: str) -> Any: ...
    @abstractmethod
    def case_ids_with_override_status(self, status: str) -> set[str]: ...
    @abstractmethod
    def all_overrides(self) -> list[Any]:
        """Every override of every case, oldest first."""

    # ── audit chain (the hash logic lives in db.audit; storage lives here) ───────────────────────────
    @abstractmethod
    def append_audit(self, actor: str, action: str, case_id: str | None, detail: dict) -> Any: ...
    @abstractmethod
    def list_audit(self, *, case_id: str | None, action: str | None, limit: int, offset: int) -> list[Any]:
        """Newest first."""
    @abstractmethod
    def audit_for_case(self, case_id: str) -> list[Any]:
        """Oldest first."""
    @abstractmethod
    def iter_audit(self) -> Iterable[Any]:
        """The whole chain, oldest first."""

    # ── policies ─────────────────────────────────────────────────────────────────────────────────────
    @abstractmethod
    def add_policy(self, plan: str, filename: str, sha256: str, uploaded_by: str) -> Any: ...
    @abstractmethod
    def get_policy(self, policy_id: int) -> Any: ...
    @abstractmethod
    def list_policies(self) -> list[Any]:
        """Newest first."""
    @abstractmethod
    def ready_policies(self) -> list[Any]:
        """Oldest first."""
    @abstractmethod
    def save_policy(self, p: Any) -> None: ...


class SqlRepo(Repo):
    def __init__(self, session: Session):
        self.s = session

    _audit_lock = threading.Lock()

    def commit(self) -> None:
        self.s.commit()

    # users
    def get_user(self, username):
        return self.s.execute(select(User).where(User.username == username)).scalar_one_or_none()

    def list_users(self):
        return list(self.s.execute(select(User).order_by(User.id)).scalars())

    def add_user(self, username, display_name, role, password_hash):
        self.s.add(User(username=username, display_name=display_name, role=role, password_hash=password_hash))

    # cases
    def get_case(self, case_id):
        return self.s.get(Case, case_id)

    def find_case_by_idempotency(self, username, key):
        return self.s.execute(select(Case).where(Case.submitted_by == username, Case.idempotency_key == key)).scalar_one_or_none()

    def add_case(self, case):
        if case.idempotency_key and (prior := self.find_case_by_idempotency(case.submitted_by, case.idempotency_key)):
            return prior, False
        self.s.add(case)
        try:
            self.s.flush()
        except IntegrityError:                                    # lost an idempotency race
            self.s.rollback()
            return self.find_case_by_idempotency(case.submitted_by, case.idempotency_key), False
        return case, True

    def save_case(self, case):
        self.s.flush()

    def save_document(self, doc):
        self.s.flush()

    def list_cases(self, *, submitted_by=None, status=None, decision=None, limit=50, offset=0):
        q = select(Case).order_by(Case.created_at.desc())
        if submitted_by:
            q = q.where(Case.submitted_by == submitted_by)
        if status:
            q = q.where(Case.status == status.upper())
        if decision:
            q = q.where(func.coalesce(Case.final_decision, Case.ai_decision) == decision.upper())
        return list(self.s.execute(q.limit(limit).offset(offset)).scalars().all())

    def all_cases(self):
        return list(self.s.execute(select(Case)).scalars().all())

    def cases_by_status(self, status):
        return list(self.s.execute(select(Case).where(Case.status == status)).scalars().all())

    def case_decisions(self, case_ids):
        ids, out = list(case_ids), {}
        for i in range(0, len(ids), 500):                     # stay under SQLite's bound-parameter limit
            rows = self.s.execute(select(Case.id, Case.decision).where(Case.id.in_(ids[i:i + 500])))
            out.update((cid, d) for cid, d in rows if d)
        return out

    # runs
    def replace_agent_runs(self, case_id, runs):
        self.s.query(AgentRunRow).filter(AgentRunRow.case_id == case_id).delete()
        for r in runs:
            self.s.add(AgentRunRow(case_id=case_id, agent=r["agent"], model=r.get("model"), retried_with=r.get("retried_with"),
                                   input_tokens=r["input_tokens"], output_tokens=r["output_tokens"], cost_usd=r["cost_usd"],
                                   cold_cost_usd=r.get("cold_cost_usd", r["cost_usd"]), latency_ms=r["latency_ms"],
                                   llm_calls=r["llm_calls"], cache_hits=r["cache_hits"]))

    def list_agent_runs(self, case_id):
        return list(self.s.execute(select(AgentRunRow).where(AgentRunRow.case_id == case_id).order_by(AgentRunRow.id)).scalars().all())

    # events
    def add_event(self, case_id, ev):
        extra = {k: v for k, v in ev.items() if k not in ("node", "status", "doc_id", "ts")}
        self.s.add(CaseEvent(case_id=case_id, node=str(ev.get("node", "")), status=str(ev.get("status", "")),
                             doc_id=ev.get("doc_id"), payload=extra))

    def events_after(self, case_id, last_id):
        return list(self.s.execute(select(CaseEvent).where(CaseEvent.case_id == case_id, CaseEvent.id > last_id)
                                   .order_by(CaseEvent.id)).scalars().all())

    def clear_events(self, case_id):
        self.s.query(CaseEvent).filter(CaseEvent.case_id == case_id).delete()

    # overrides
    def add_override(self, ov):
        self.s.add(ov)
        self.s.flush()
        return ov

    def get_override(self, case_id, override_id):
        ov = self.s.get(Override, override_id)
        return ov if ov is not None and ov.case_id == case_id else None

    def list_overrides(self, case_id):
        return list(self.s.execute(select(Override).where(Override.case_id == case_id).order_by(Override.id)).scalars().all())

    def save_override(self, ov):
        self.s.flush()

    def pending_override(self, case_id):
        return self.s.execute(select(Override).where(Override.case_id == case_id, Override.status == "PENDING_APPROVAL")).scalar_one_or_none()

    def case_ids_with_override_status(self, status):
        return set(self.s.execute(select(Override.case_id).where(Override.status == status)).scalars())

    def all_overrides(self):
        return list(self.s.execute(select(Override).order_by(Override.id)).scalars().all())

    # audit
    def append_audit(self, actor, action, case_id, detail):
        from medishield.db import audit as chain

        with self._audit_lock:
            head = self.s.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
            prev = head.hash if head else chain.GENESIS
            ts = utcnow().isoformat(timespec="microseconds")
            ev = AuditEvent(ts=ts, actor=actor, action=action, case_id=case_id, detail=detail, prev_hash=prev,
                            hash=chain.chain_hash(prev, chain.canonical(ts, actor, action, case_id, detail)))
            self.s.add(ev)
            self.s.flush()
        return ev

    def list_audit(self, *, case_id, action, limit, offset):
        q = select(AuditEvent).order_by(AuditEvent.seq.desc())
        if case_id:
            q = q.where(AuditEvent.case_id == case_id)
        if action:
            q = q.where(AuditEvent.action == action)
        return list(self.s.execute(q.limit(limit).offset(offset)).scalars())

    def audit_for_case(self, case_id):
        return list(self.s.execute(select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.seq)).scalars().all())

    def iter_audit(self):
        return self.s.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars()

    # policies
    def add_policy(self, plan, filename, sha256, uploaded_by):
        p = PolicyDoc(plan=plan, filename=filename[:255], sha256=sha256, uploaded_by=uploaded_by, status="INGESTING")
        self.s.add(p)
        self.s.flush()
        return p

    def get_policy(self, policy_id):
        return self.s.get(PolicyDoc, policy_id)

    def list_policies(self):
        return list(self.s.execute(select(PolicyDoc).order_by(PolicyDoc.id.desc())).scalars())

    def ready_policies(self):
        return list(self.s.execute(select(PolicyDoc).where(PolicyDoc.status == "READY").order_by(PolicyDoc.id)).scalars().all())

    def save_policy(self, p):
        self.s.flush()


# ── obtaining a repo ──────────────────────────────────────────────────────────────────────────────────
def backend() -> str:
    from medishield.config import get_settings

    return get_settings().db_backend


@contextmanager
def repo_scope() -> Iterator[Repo]:
    """A repo that commits on success and rolls back on error (worker code, startup tasks, request dependencies)."""
    if backend() == "dynamodb":
        from medishield.db.dynamo import get_dynamo_repo

        yield get_dynamo_repo()
        return
    from medishield.db.session import session_scope

    with session_scope() as session:
        yield SqlRepo(session)
