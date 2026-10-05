"""Deterministic decision engine: facts + decision_policy.yaml -> decision. Pure and unit-tested.

Nothing an LLM writes can reach this function except through typed, validated facts (flags, scores,
confidences), so prompt-injected text such as "APPROVED" on a document cannot flip a decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from medishield.config import get_settings
from medishield.schemas import Decision


@dataclass
class Facts:
    """Everything the decision may depend on, for one document. N/A agents simply contribute nothing."""
    doc_unknown: bool = False
    classifier_confidence: float = 1.0
    agent_confidences: dict[str, float] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)          # e.g. kyc_failed, schema_invalid, coverage_conditional
    fraud_score: float = 0.0
    reasons: list[str] = field(default_factory=list)      # human-readable evidence behind each flag


@dataclass
class Outcome:
    decision: Decision
    rule_id: str
    triggered: list[str]


@lru_cache
def load_policy(path: str | None = None) -> dict:
    return yaml.safe_load(Path(path or get_settings().decision_policy).read_text())


def _predicates(f: Facts, policy: dict) -> dict[str, bool]:
    t = policy["thresholds"]
    low = [a for a, c in f.agent_confidences.items() if c < t["agent_min_confidence"]]
    return {
        "doc_unknown": f.doc_unknown,
        "classifier_low_confidence": f.classifier_confidence < t["classifier_min_confidence"],
        "fraud_high": f.fraud_score >= t["fraud_escalate"],
        "agent_low_confidence": bool(low),
        "always": True,
    }


def _flag_lists(policy: dict) -> dict[str, set[str]]:
    hard = set(policy["hard_fail_flags"])
    soft = set(policy.get("escalate_flags", []))
    if policy.get("tamper_action", "REJECT") == "REJECT":
        hard.add("tamper_suspected")
    else:
        soft.add("tamper_suspected")
    return {"hard_fail_flags": hard, "escalate_flags": soft}


def _eval(cond, preds: dict[str, bool], flags: set[str], lists: dict[str, set[str]], hits: list[str]) -> bool:
    if cond == "always":
        return True
    if isinstance(cond, str):
        if preds.get(cond):
            hits.append(cond)
            return True
        return False
    if "any" in cond:
        # a list, not a generator: evaluate every branch so all triggered reasons are recorded in ``hits``
        return any([_eval(c, preds, flags, lists, hits) for c in cond["any"]])  # noqa: C419
    if "any_flag_in" in cond:
        matched = sorted(flags & lists[cond["any_flag_in"]])
        hits.extend(matched)
        return bool(matched)
    raise ValueError(f"unknown condition {cond!r}")


def decide(f: Facts, policy: dict | None = None) -> Outcome:
    policy = policy or load_policy()
    preds = _predicates(f, policy)
    lists = _flag_lists(policy)
    for rule in policy["rules"]:
        hits: list[str] = []
        if _eval(rule["when"], preds, f.flags, lists, hits):
            return Outcome(Decision(rule["decision"]), rule["id"], hits)
    raise RuntimeError("decision policy has no default rule")


def decision_confidence(f: Facts, o: Outcome, policy: dict | None = None) -> float:
    """How strongly the evidence supports *this* decision (calibrated against accuracy at checkpoint 5)."""
    policy = policy or load_policy()
    confs = list(f.agent_confidences.values()) or [f.classifier_confidence]
    if o.rule_id.startswith("R1"):
        return round(f.classifier_confidence if f.doc_unknown else 1 - f.classifier_confidence, 3)
    if o.decision == Decision.REJECT:
        return round(max(confs), 3)
    if o.decision == Decision.ESCALATE:
        if "fraud_high" in o.triggered:
            return round(min(0.95, 0.5 + f.fraud_score / 2), 3)
        if "agent_low_confidence" in o.triggered:
            return round(1 - min(confs), 3)
        return 0.8
    return round(min(confs) * (1 - f.fraud_score), 3)


def rollup(decisions: list[Decision]) -> Decision:
    """Case roll-up: any ESCALATE -> ESCALATE; else any REJECT -> REJECT; else APPROVE."""
    if Decision.ESCALATE in decisions:
        return Decision.ESCALATE
    if Decision.REJECT in decisions:
        return Decision.REJECT
    return Decision.APPROVE
