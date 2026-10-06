"""Data tools for the assistant. Each returns numbered *passages* the answer cites as [n], and each enforces access itself.

Hard boundaries (they hold even if the router is fooled):
* cases: a user without ``case:read_all`` only ever receives their own cases; any other id is "not visible", whether or not it
  exists (no existence leak);
* audit and review data need ``audit:read`` / ``review:queue``;
* every passage records whose data it is, and ``guard`` refuses to hand the model anything outside the caller's scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from medishield.api.security import Principal
from medishield.chat import access
from medishield.db.repo import Repo


class LeakError(RuntimeError):
    """A passage outside the caller's scope reached the answer step. A bug alarm; never expected to fire."""


@dataclass
class Passage:
    kind: str                       # policy | exclusion | case | audit | review | data
    title: str
    text: str
    url: str | None = None          # deep link in the UI
    page: int | None = None
    owner: str | None = None        # submitter of the case the passage describes (None = not case data)
    permission: str = "policy:ask"  # permission needed to see it
    meta: dict = field(default_factory=dict)


def guard(user: Principal, passages: list[Passage]) -> list[Passage]:
    for p in passages:
        if not access.allowed(user.role, p.permission):
            raise LeakError(f"{p.kind} passage needs {p.permission}")
        if p.owner is not None and access.own_cases_only(user.role) and p.owner != user.username:
            raise LeakError(f"case passage owned by another user reached {user.username}")
    return passages


# ── policies ─────────────────────────────────────────────────────────────────────────────────────────
def policy_passages(question: str, plans: list[str], codes: list[str], k: int = 3) -> list[Passage]:
    from medishield.rag.exclusions import lookup
    from medishield.rag.retrieve import get_store

    store = get_store()
    plans = [p for p in plans if p in store.indexes] or sorted(store.indexes)
    out: list[Passage] = []
    for plan in plans:
        for code in codes:                                      # the parsed exclusion table is authoritative for coverage
            rows = lookup(code, store.ranges(plan))
            text = ("; ".join(f"{r.label} ({r.kind.replace('_', ' ')}: {r.category}, basis: {r.basis})" for r in rows) if rows
                    else "not listed in table 4.1 (no exclusion or prior-authorisation range)")
            out.append(Passage("exclusion", f"{plan.title()} plan, table 4.1 - CPT {code}", f"CPT {code}: {text}",
                               page=rows[0].page if rows else None, meta={"plan": plan, "code": code, "excluded": bool(rows)}))
        if codes or re.search(r"\b(pay|cost|copay|coinsurance|deductible|out-of-pocket|percent|%)", question, re.IGNORECASE):
            for c in store.indexes[plan].chunks:                # the Schedule of Benefits: cost sharing per benefit category
                if c.section_no == "1" and c.kind == "table":
                    out.append(Passage("policy", f"{plan.title()} plan, {c.section} (cost sharing by benefit category)",
                                       c.text[:2500], page=c.pages[0] if c.pages else None, meta={"plan": plan}))
        seen = {p.title for p in out}
        for h in store.search(question, plan, k=k):
            c = h.chunk
            if c.section_no == "1" and c.kind == "table" and any(t.startswith(f"{plan.title()} plan, {c.section}") for t in seen):
                continue
            out.append(Passage("policy", f"{plan.title()} plan, {c.section}" + (f" > {c.subsection}" if c.subsection else ""),
                               c.text[:1500], page=c.pages[0] if c.pages else None, meta={"plan": plan, "score": round(h.score, 3)}))
    return out


# ── cases ────────────────────────────────────────────────────────────────────────────────────────────
def _visible(user: Principal, case) -> bool:
    return case is not None and (not access.own_cases_only(user.role) or case.submitted_by == user.username)


def case_passages(user: Principal, repo: Repo, case_ids: list[str]) -> tuple[list[Passage], list[str]]:
    """(passages, ids that are not visible to this user)."""
    out, hidden = [], []
    for cid in case_ids[:5]:
        case = repo.get_case(cid)
        if not _visible(user, case):
            hidden.append(cid)
            continue
        dec, fraud = case.decision or {}, case.fraud or {}
        summary = (f"Case {case.id}: status {case.status}; automated decision {case.ai_decision} "
                   f"(confidence {case.ai_confidence or 0:.2f}); final decision {case.final_decision or 'pending'}; "
                   f"claimed amount ${case.total_amount:,.2f}; fraud risk {fraud.get('risk_level', '-')} ({case.risk_score:.2f}); "
                   f"submitted by {case.submitted_by} on {case.created_at:%Y-%m-%d}.")
        lines = [summary]
        if dec.get("justification"):
            lines.append(f"Justification: {dec['justification']}")
        for d in dec.get("documents", []):
            lines.append(f"- {d['doc_id']} ({d.get('doc_type')}): {d['decision']} by rule {d.get('rule_id')}; "
                         f"reasons: {'; '.join(d.get('reasons', [])[:4])}")
        for a in fraud.get("anomalies", [])[:5]:
            lines.append(f"- fraud signal {a.get('code') or a.get('type')}: {a.get('detail') or a.get('description', '')}"[:300])
        for doc in case.documents:
            pol = (doc.specialists or {}).get("policy") if doc.specialists else None
            if pol:
                codes = ", ".join(f"{p['code']} {p['status']}" for p in pol.get("per_code", []))
                lines.append(f"- policy check on {doc.doc_id}: {pol.get('coverage_status')}; {codes}; clause: {pol.get('policy_clause', '')[:200]}")
            kyc = (doc.specialists or {}).get("kyc") if doc.specialists else None
            if kyc:
                lines.append(f"- KYC on {doc.doc_id}: {'passed' if kyc.get('kyc_passed') else 'failed'}; flags {kyc.get('flags')}; "
                             f"warnings {kyc.get('warnings')}")
        out.append(Passage("case", f"Case {case.id}", "\n".join(lines), url=f"/cases/view?id={case.id}", owner=case.submitted_by,
                           permission="case:read"))
        if access.allowed(user.role, "review:queue"):
            for ov in repo.list_overrides(case.id):
                out.append(Passage("review", f"Override #{ov.id} on {case.id}",
                                   f"{ov.requested_by} requested {ov.decision} ({ov.reason_code}); status {ov.status}; "
                                   f"four-eyes {'yes' if ov.requires_four_eyes else 'no'}; resolved by {ov.resolved_by or '-'}",
                                   url=f"/cases/view?id={case.id}", owner=case.submitted_by, permission="review:queue"))
    return out, hidden


def my_cases_passage(user: Principal, repo: Repo, limit: int = 15) -> list[Passage]:
    rows = repo.list_cases(submitted_by=user.username if access.own_cases_only(user.role) else None, limit=limit)
    text = "\n".join(f"- {c.id}: {c.status}, decision {c.final_decision or c.ai_decision or 'pending'}, "
                     f"${c.total_amount:,.2f}, {c.created_at:%Y-%m-%d}" for c in rows) or "no cases"
    title = "Your most recent cases" if access.own_cases_only(user.role) else "Most recent cases"
    return [Passage("case", title, text, url="/", owner=user.username if access.own_cases_only(user.role) else None,
                    permission="case:read")]


# ── audit and review ─────────────────────────────────────────────────────────────────────────────────
def audit_passages(user: Principal, repo: Repo, case_ids: list[str], limit: int = 25) -> list[Passage]:
    if not access.allowed(user.role, "audit:read"):
        return []
    events = [e for cid in case_ids[:3] for e in repo.audit_for_case(cid)] if case_ids else \
        repo.list_audit(case_id=None, action=None, limit=limit, offset=0)
    text = "\n".join(f"- #{e.seq} {e.ts[:19]} {e.actor} {e.action}" + (f" on {e.case_id}" if e.case_id else "")
                     + (f" {str(e.detail)[:120]}" if e.detail else "") for e in events[-limit:]) or "no audit events"
    return [Passage("audit", "Audit trail" + (f" for {', '.join(case_ids[:3])}" if case_ids else " (latest events)"), text,
                    url="/audit", permission="audit:read")]


def review_passages(user: Principal, repo: Repo) -> list[Passage]:
    if not access.allowed(user.role, "review:queue"):
        return []
    pending = repo.case_ids_with_override_status("PENDING_APPROVAL")
    rows = repo.cases_by_status("IN_REVIEW")
    text = "\n".join(f"- {c.id}: ${c.total_amount:,.2f}, risk {c.risk_score:.2f}, since {c.created_at:%Y-%m-%d %H:%M}"
                     + (" - override awaiting second approver" if c.id in pending else "") for c in rows) or "the queue is empty"
    return [Passage("review", f"Review queue ({len(rows)} cases)", text, url="/review", permission="review:queue")]
