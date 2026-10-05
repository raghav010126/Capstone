import itertools

import pytest
from medishield.decision.engine import Facts, decide, decision_confidence, load_policy, rollup
from medishield.schemas import Decision

A, R, E = Decision.APPROVE, Decision.REJECT, Decision.ESCALATE


def facts(**kw) -> Facts:
    f = Facts(agent_confidences={"extractor": 0.95})
    for k, v in kw.items():
        setattr(f, k, v)
    return f


def test_clean_document_is_approved():
    out = decide(facts())
    assert (out.decision, out.rule_id) == (A, "R4_default")


@pytest.mark.parametrize("flag", ["kyc_failed", "procedure_not_covered", "schema_invalid", "tamper_suspected"])
def test_each_hard_failure_rejects(flag):
    out = decide(facts(flags={flag}))
    assert out.decision == R and out.rule_id == "R2_hard_failure" and flag in out.triggered


def test_unknown_document_escalates():
    assert decide(facts(doc_unknown=True)).rule_id == "R1_unknown_or_unclassified"


def test_low_classifier_confidence_escalates():
    assert decide(facts(classifier_confidence=0.59)).decision == E
    assert decide(facts(classifier_confidence=0.60)).decision == A


def test_fraud_threshold_is_inclusive():
    assert decide(facts(fraud_score=0.3)).decision == E
    assert decide(facts(fraud_score=0.299)).decision == A


def test_any_low_agent_confidence_escalates():
    out = decide(facts(agent_confidences={"extractor": 0.95, "kyc": 0.55}))
    assert out.decision == E and "agent_low_confidence" in out.triggered


@pytest.mark.parametrize("flag", ["coverage_conditional", "agent_failed"])
def test_soft_flags_escalate(flag):
    assert decide(facts(flags={flag})).decision == E


def test_hard_failure_beats_fraud():
    """C_012: an uncovered $9,950 claim also looks like structuring -> REJECT wins (brief's precedence)."""
    out = decide(facts(flags={"procedure_not_covered"}, fraud_score=0.9))
    assert out.decision == R


def test_unknown_beats_everything():
    out = decide(facts(doc_unknown=True, flags={"schema_invalid"}, fraud_score=0.9))
    assert out.rule_id.startswith("R1")


def test_precedence_property_over_all_combinations():
    """Exhaustive: the outcome always equals the brief's precedence order."""
    for unknown, low_cls, hard, soft, fraud, low_agent in itertools.product([False, True], repeat=6):
        f = facts(doc_unknown=unknown, classifier_confidence=0.4 if low_cls else 0.9,
                  flags=({"schema_invalid"} if hard else set()) | ({"coverage_conditional"} if soft else set()),
                  fraud_score=0.5 if fraud else 0.0,
                  agent_confidences={"x": 0.4 if low_agent else 0.9})
        expected = E if (unknown or low_cls) else R if hard else E if (soft or fraud or low_agent) else A
        assert decide(f).decision == expected


def test_tamper_policy_is_configurable():
    policy = dict(load_policy())
    policy["tamper_action"] = "ESCALATE"
    assert decide(facts(flags={"tamper_suspected"}), policy).decision == E


def test_rollup():
    assert rollup([A, A]) == A
    assert rollup([A, R]) == R
    assert rollup([R, E, A]) == E


def test_confidence_in_unit_interval():
    for f in (facts(), facts(flags={"schema_invalid"}), facts(fraud_score=0.6), facts(doc_unknown=True)):
        assert 0.0 <= decision_confidence(f, decide(f)) <= 1.0
