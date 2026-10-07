"""Real graph routing and decision rules, with only perception/model/retrieval IO stubbed."""
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from medishield.agents import policy
from medishield.agents.claims import validate_claim
from medishield.agents.context import CaseContext
from medishield.agents.kyc import verify_claim
from medishield.agents.orchestrator import build_facts
from medishield.decision.engine import decide
from medishield.graph import build
from medishield.llm import LLMError
from medishield.records import Records
from medishield.schemas import AgentRun, Classification, DocType, ExtractionResult
from medishield.schemas.llm_outputs import PolicyRead
from test_rules import GOOD_CLAIM, MEMBER, RANGES


def extraction(values=None):
    return ExtractionResult(doc_type=DocType.CLAIM_FORM, values=deepcopy(GOOD_CLAIM if values is None else values),
                            fields=[], raw_text="", bounding_boxes=[], grounding_rate=1, support_rate=1, confidence=.95)


def classification(dtype=DocType.CLAIM_FORM):
    return Classification(doc_type=dtype, confidence=.95, routing_tags=[], llm_doc_type=dtype,
                          llm_self_confidence=.95, keyword_doc_type=dtype, keyword_margin=1, reason="fixture")


class Store:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.chunk = NS(chunk_id="gold-1", plan="gold", section="1 Schedule of Benefits", section_no="1",
                        kind="table", pages=[2], subsection="", text="Category | Share\n--- | ---\nOffice | 20%")
        self.indexes = {} if mode == "unavailable" else {"gold": NS(chunks=[self.chunk])}

    def ranges(self, plan):
        return RANGES

    def search(self, query, plan, k):
        assert plan == "gold"
        if self.mode == "error":
            raise RuntimeError("index unavailable")
        if self.mode == "empty":
            return []
        if self.mode == "wrong_plan":
            return [NS(chunk=NS(**{**vars(self.chunk), "plan": "silver"}), score=1)]
        return [NS(chunk=self.chunk, score=1)]


def model(monkeypatch, mode="ok"):
    def read(*args, **kwargs):
        if mode == "error":
            raise LLMError("offline")
        codes = [] if mode == "omitted" else [{"code": c, "benefit_category": "Office", "coverage_status": "COVERED",
                  "conditions": [], "citation_section": "1", "citation_page": 2, "rationale": "office benefit"} for c in ("99213", "85025")]
        return NS(parsed=PolicyRead(codes=codes, summary="fixture"), run=lambda name: AgentRun(agent=name))
    monkeypatch.setattr(policy, "structured", read)


@pytest.mark.parametrize("mode", ["error", "omitted", "empty", "unavailable", "wrong_plan", "retrieval_error"])
def test_policy_failure_never_implies_coverage(monkeypatch, mode):
    model(monkeypatch, mode if mode in {"error", "omitted"} else "ok")
    store = Store("error" if mode == "retrieval_error" else mode if mode not in {"error", "omitted"} else "ok")
    result, _ = policy.run_policy(extraction(), CaseContext("C"), Records([MEMBER], []), store)
    assert result.coverage_status == "CONDITIONAL"
    assert all(c.status == "CONDITIONAL" for c in result.per_code)


@pytest.mark.parametrize("code,status", [("15822", "NOT_COVERED"), ("97110", "CONDITIONAL")])
def test_authoritative_table_survives_model_failure(monkeypatch, code, status):
    model(monkeypatch, "error")
    result, _ = policy.run_policy(extraction(GOOD_CLAIM | {"service_lines": [{"cpt": code, "charge": 175}]}),
                                  CaseContext("C"), Records([MEMBER], []), Store())
    assert result.coverage_status == status


def test_unknown_plan_and_no_codes_need_review(monkeypatch):
    model(monkeypatch)
    for values in (GOOD_CLAIM | {"policy_number": "UNRECOGNIZED", "patient_name": "Unknown"},
                   GOOD_CLAIM | {"service_lines": []}):
        result, _ = policy.run_policy(extraction(values), CaseContext("C"), Records([MEMBER], []), Store())
        assert result.coverage_status == "CONDITIONAL"


@pytest.mark.parametrize("changes", [{"policy_number": "MED-GLD-UNKNOWN"}, {"patient_name": "Bob Smith"},
                                    {"patient_dob": "01/02/1990"}, {"patient_dob": None}, {"patient_name": "Ann Leee"}])
def test_claim_identity_uncertainty_needs_review(changes):
    result = verify_claim(extraction(GOOD_CLAIM | changes), Records([MEMBER], []))
    assert not result.kyc_passed and not result.flags and result.confidence < .6


@pytest.mark.parametrize("field,value", [("total_charge", -175), ("total_charge", 0), ("total_charge", float("inf")),
                                       ("total_charge", float("nan")), ("line", -1), ("line", None),
                                       ("line", float("inf")), ("line", float("nan"))])
def test_invalid_money_fails_standard(field, value):
    import math

    from medishield.services.cases import case_total

    claim = deepcopy(GOOD_CLAIM)
    if field == "line":
        claim["service_lines"][0]["charge"] = value
    else:
        claim[field] = value
    assert validate_claim(claim)[0]
    aggregate = case_total([NS(doc_type="CLAIM_FORM", extraction={"values": claim}, doc_id="d")])
    assert math.isfinite(aggregate) and aggregate >= 0


def test_zero_line_in_positive_claim_is_valid():
    claim = GOOD_CLAIM | {"service_lines": [{"cpt": "99213", "charge": 0}, {"cpt": "85025", "charge": 175}]}
    assert validate_claim(claim)[0] == []


@pytest.mark.parametrize("missing", ["extraction", "kyc", "claims", "policy", "fraud"])
def test_missing_required_result_blocks_approval(monkeypatch, missing):
    model(monkeypatch)
    ext = extraction()
    pol, _ = policy.run_policy(ext, CaseContext("C"), Records([MEMBER], []), Store())
    from medishield.agents.claims import run_claims
    from medishield.schemas import FraudResult
    results = {"extraction": ext, "kyc": verify_claim(ext, Records([MEMBER], [])),
                   "claims": run_claims(DocType.CLAIM_FORM, ext), "policy": pol,
                   "fraud": FraudResult(fraud_score=0, per_doc_score={"d": 0}, anomalies=[], risk_level="LOW")}
    results[missing] = None
    facts = build_facts("d", classification(), results["extraction"], results["kyc"], results["claims"],
                        results["policy"], results["fraud"], [])
    assert decide(facts).decision == "ESCALATE"
    if missing == "fraud":
        empty = FraudResult(fraud_score=0, per_doc_score={}, anomalies=[], risk_level="LOW")
        facts = build_facts("d", classification(), ext, results["kyc"], results["claims"], pol, empty, [])
        assert decide(facts).decision == "ESCALATE"


@pytest.mark.parametrize("scenario,expected", [("valid", "APPROVE"), ("unknown_member", "ESCALATE"),
    ("inactive", "REJECT"), ("policy_error", "ESCALATE"), ("missing_extraction", "ESCALATE"), ("negative", "REJECT")])
def test_claim_only_real_graph(monkeypatch, scenario, expected):
    model(monkeypatch, "error" if scenario == "policy_error" else "ok")
    values = deepcopy(GOOD_CLAIM)
    if scenario == "unknown_member":
        values["policy_number"] = "MED-GLD-UNKNOWN"
    if scenario == "negative":
        values["total_charge"] = -175
    rec = Records([MEMBER | {"status": "INACTIVE" if scenario == "inactive" else "ACTIVE"}], [])
    def perceive(task):
        p = {"classification": classification().model_dump(mode="json"), "failed": []}
        if scenario != "missing_extraction":
            p["extraction"] = extraction(values).model_dump(mode="json")
        return {"perception": {task["doc"]["doc_id"]: p}}
    monkeypatch.setattr(build, "perceive", perceive)
    graph = build.build_graph()
    state = graph.invoke({"case_id": "C", "documents": [{"doc_id": "d", "path": "unused"}]},
                         {"configurable": {"thread_id": scenario, "records": rec, "store": Store()}})
    assert state["decision"]["decision"] == expected
    if scenario == "valid":
        assert state["specialists"]["d"]["kyc"]["kyc_passed"]
