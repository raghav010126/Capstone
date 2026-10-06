"""AI quality monitor: how human reviewers agree with the AI, computed from what is already recorded (no model calls).

Sources: case records (AI decision, confidence, final decision and the rule each document decision came from), override
records (reason code, four-eyes outcome, resolution time) and ``document_reclassified`` audit events.

Windows are cohorts by case creation: "last 30 days" covers cases created in the last 30 days, with their overrides and
reclassifications, so every rate has the same denominator whichever window is shown.

Definitions
* decided: the AI reached a decision (status DECIDED, IN_REVIEW or FINALIZED).
* human-reviewed: routed to a person (IN_REVIEW or FINALIZED) or carrying any override request.
* human-resolved: a person set the final decision (FINALIZED).
* agreement: final decision == AI decision, among human-resolved cases. An ESCALATE hands the decision to a person, so
  ``agreement_rate_approve_reject`` repeats the measure on cases where the AI itself chose APPROVE or REJECT.
* the rules that drove a case: the ``rule_id`` of each document whose decision equals the case decision (the roll-up is
  "any ESCALATE, else any REJECT, else APPROVE", so those documents decided the case).
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from medishield.db.repo import Repo
from medishield.services.review import REASON_CODES

DONE = ("DECIDED", "IN_REVIEW", "FINALIZED")
WINDOW_DAYS = 30
MAX_AUDIT_ROWS = 1_000_000


class ReasonCount(BaseModel):
    reason_code: str
    label: str
    requested: int = Field(description="override requests with this reason, whatever their outcome")
    applied: int


class RuleOverrides(BaseModel):
    rule_id: str
    decision: str = Field(description="the AI decision this rule produces")
    cases: int = Field(description="decided cases this rule drove")
    overridden: int = Field(description="of those, cases with an applied override")
    changed: int = Field(description="of those, cases whose final human decision differs from the AI's")
    change_rate: float | None = Field(description="changed / cases")


class Transition(BaseModel):
    ai_decision: str
    final_decision: str
    cases: int


class ConfidenceSplit(BaseModel):
    confirmed: float | None = Field(description="mean AI confidence where the human kept the AI decision")
    overridden: float | None = Field(description="mean AI confidence where the human changed it")
    n_confirmed: int
    n_overridden: int


class Reclassification(BaseModel):
    from_type: str
    to_type: str
    count: int


class FourEyes(BaseModel):
    requested: int
    approved: int
    rejected: int
    pending: int


class QualityWindow(BaseModel):
    since: datetime | None = Field(description="cohort start (cases created on or after); null for all time")
    cases_decided: int
    escalation_rate: float | None
    human_reviewed: int
    awaiting_review: int
    human_resolved: int
    overrides_applied: int
    applied_override_rate: float | None = Field(description="decided cases with an applied override / cases decided")
    agreement_rate: float | None
    agreement_rate_approve_reject: float | None
    reason_codes: list[ReasonCount]
    rules: list[RuleOverrides]
    transitions: list[Transition]
    confidence: ConfidenceSplit
    reclassifications: int
    reclassification_types: list[Reclassification]
    four_eyes: FourEyes
    median_hours_to_final: float | None = Field(description="case creation to the applied override that finalised it")


class QualityOut(BaseModel):
    generated_at: datetime
    window_days: int
    all_time: QualityWindow
    recent: QualityWindow


def _rate(n: int, d: int, digits: int = 4) -> float | None:
    return round(n / d, digits) if d else None


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 3) if xs else None


def driving_rules(decision: dict | None) -> dict[str, str]:
    """rule_id -> decision for the documents that decided the case (all documents if none matches the case decision)."""
    if not decision:
        return {}
    docs = [d for d in decision.get("documents") or [] if d.get("rule_id")]
    hit = [d for d in docs if d.get("decision") == decision.get("decision")] or docs
    return {d["rule_id"]: d.get("decision") or decision.get("decision") or "" for d in hit}


def summarise(cases: list[Any], decisions: dict[str, dict], overrides: list[Any], reclassified: list[Any],
              since: datetime | None = None) -> QualityWindow:
    """One window's metrics. Inputs are what the repo returns; filtering to the cohort happens here."""
    if since is not None:
        cases = [c for c in cases if c.created_at and c.created_at >= since]
    ids = {c.id for c in cases}
    overrides = [o for o in overrides if o.case_id in ids]
    reclassified = [e for e in reclassified if e.case_id in ids]
    by_case: dict[str, list[Any]] = defaultdict(list)
    for o in overrides:
        by_case[o.case_id].append(o)

    decided = [c for c in cases if c.status in DONE and c.ai_decision]
    applied_cases = {o.case_id for o in overrides if o.status == "APPLIED"}
    reviewed = [c for c in decided if c.status in ("IN_REVIEW", "FINALIZED") or c.id in by_case]
    resolved = [c for c in decided if c.status == "FINALIZED" and c.final_decision]
    changed_ids = {c.id for c in resolved if c.final_decision != c.ai_decision}
    agree = [c for c in resolved if c.final_decision == c.ai_decision]
    committed = [c for c in resolved if c.ai_decision in ("APPROVE", "REJECT")]

    rules: dict[str, dict] = {}
    for c in decided:
        changed = c.id in changed_ids
        for rule_id, dec in driving_rules(decisions.get(c.id)).items():
            r = rules.setdefault(rule_id, {"decision": dec, "cases": 0, "overridden": 0, "changed": 0})
            r["cases"] += 1
            r["overridden"] += c.id in applied_cases
            r["changed"] += changed
    rule_rows = [RuleOverrides(rule_id=k, change_rate=_rate(v["changed"], v["cases"]), **v) for k, v in rules.items()]
    rule_rows.sort(key=lambda r: (-r.changed, -r.overridden, -r.cases, r.rule_id))

    requested, applied = Counter(o.reason_code for o in overrides), Counter(o.reason_code for o in overrides if o.status == "APPLIED")
    reasons = [ReasonCount(reason_code=k, label=REASON_CODES.get(k, k), requested=n, applied=applied[k])
               for k, n in sorted(requested.items(), key=lambda kv: (-kv[1], kv[0]))]

    moves = Counter((c.ai_decision, c.final_decision) for c in resolved)
    transitions = [Transition(ai_decision=a, final_decision=f, cases=n) for (a, f), n in sorted(moves.items(), key=lambda kv: (-kv[1], kv[0]))]

    kept = [c.ai_confidence for c in agree if c.ai_confidence is not None]
    changed_conf = [c.ai_confidence for c in resolved if c.final_decision != c.ai_decision and c.ai_confidence is not None]

    types = Counter((str(e.detail.get("from") or "UNCLASSIFIED"), str(e.detail.get("to") or "UNCLASSIFIED")) for e in reclassified)

    four = [o for o in overrides if o.requires_four_eyes]
    status = Counter(o.status for o in four)

    hours = []
    for c in resolved:
        done = [o.resolved_at for o in by_case.get(c.id, []) if o.status == "APPLIED" and o.resolved_at]
        if done and c.created_at:
            hours.append(max(0.0, (max(done) - c.created_at).total_seconds() / 3600))

    return QualityWindow(
        since=since, cases_decided=len(decided),
        escalation_rate=_rate(sum(c.ai_decision == "ESCALATE" for c in decided), len(decided)),
        human_reviewed=len(reviewed), awaiting_review=sum(c.status == "IN_REVIEW" for c in decided),
        human_resolved=len(resolved), overrides_applied=sum(o.status == "APPLIED" for o in overrides),
        applied_override_rate=_rate(sum(c.id in applied_cases for c in decided), len(decided)),
        agreement_rate=_rate(len(agree), len(resolved)),
        agreement_rate_approve_reject=_rate(sum(c.final_decision == c.ai_decision for c in committed), len(committed)),
        reason_codes=reasons, rules=rule_rows, transitions=transitions,
        confidence=ConfidenceSplit(confirmed=_mean(kept), overridden=_mean(changed_conf), n_confirmed=len(kept),
                                   n_overridden=len(changed_conf)),
        reclassifications=len(reclassified),
        reclassification_types=[Reclassification(from_type=a, to_type=b, count=n)
                                for (a, b), n in sorted(types.items(), key=lambda kv: (-kv[1], kv[0]))],
        four_eyes=FourEyes(requested=len(four), approved=status["APPLIED"], rejected=status["REJECTED"],
                           pending=status["PENDING_APPROVAL"]),
        median_hours_to_final=round(statistics.median(hours), 2) if hours else None,
    )


def _overrides(db: Repo, cases: Iterable[Any]) -> list[Any]:
    overrides = db.all_overrides()
    seen = {o.case_id for o in overrides}
    # a finalised case always has an applied override; if none came back (an older DynamoDB override written before the
    # status markers existed) read that case's overrides directly. Never triggers on SQL or on newer data.
    for c in cases:
        if c.status == "FINALIZED" and c.id not in seen:
            overrides += db.list_overrides(c.id)
    return overrides


def compute_quality(db: Repo, now: datetime | None = None, window_days: int = WINDOW_DAYS) -> QualityOut:
    """A handful of reads whatever the number of cases: case headers, the decisions of decided cases (batched), every
    override, and the reclassification events."""
    now = now or datetime.now(UTC)
    cases = db.case_headers()
    decisions = db.case_decisions([c.id for c in cases if c.status in DONE and c.ai_decision])
    overrides = _overrides(db, cases)
    reclassified = db.list_audit(case_id=None, action="document_reclassified", limit=MAX_AUDIT_ROWS, offset=0)
    return QualityOut(generated_at=now, window_days=window_days,
                      all_time=summarise(cases, decisions, overrides, reclassified),
                      recent=summarise(cases, decisions, overrides, reclassified, since=now - timedelta(days=window_days)))
