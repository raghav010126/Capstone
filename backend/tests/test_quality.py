"""AI quality monitor (GET /ops/quality): human-AI agreement from recorded overrides and audit events. Runs on SQL and on
DynamoDB (``MEDISHIELD_TEST_DB=dynamodb``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import upload

RULE = {"APPROVE": "R4_default", "REJECT": "R2_hard_failure", "ESCALATE": "R3_fraud_or_low_confidence"}
CONF = {"APPROVE": 0.95, "REJECT": 0.9, "ESCALATE": 0.5}


@pytest.fixture
def ruled(fake_pipeline, monkeypatch):
    """The fake pipeline, with the rule ids and confidences the real engine would give each decision. A REJECT case also
    carries an approved second document, which must not count as a rule that drove the case."""
    from medishield import pipeline

    inner = pipeline.run_case_stream

    def run(*a, **kw):
        out = inner(*a, **kw)
        dec = out["values"]["decision"]
        dec["confidence"] = CONF[dec["decision"]]
        for i, d in enumerate(dec["documents"]):
            if dec["decision"] == "REJECT" and i > 0:
                d["decision"] = "APPROVE"
            d["rule_id"] = RULE[d["decision"]]
        return out

    monkeypatch.setattr(pipeline, "run_case_stream", run)
    return fake_pipeline


def new_case(client, auth, fake, decision: str, amount: float = 500.0) -> str:
    fake.decision, fake.amount = decision, amount
    return upload(client, auth("submitter")).json()["case_id"]


def override(client, headers, cid, decision, reason):
    r = client.post(f"/cases/{cid}/override", json={"decision": decision, "reason_code": reason, "note": ""}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def age(case_id: str, delta: timedelta) -> None:
    from medishield.db.repo import repo_scope

    with repo_scope() as db:
        c = db.get_case(case_id)
        c.created_at = c.created_at - delta
        db.save_case(c)


def test_quality_requires_ops_read(client, auth, fake_pipeline):
    assert client.get("/ops/quality", headers=auth("submitter")).status_code == 403
    assert client.get("/ops/quality").status_code == 401
    for role in ("reviewer", "senior", "auditor", "admin"):
        assert client.get("/ops/quality", headers=auth(role)).status_code == 200


def test_quality_is_empty_before_any_case(client, auth, fake_pipeline):
    q = client.get("/ops/quality", headers=auth("auditor")).json()
    assert q["window_days"] == 30 and q["all_time"]["since"] is None and q["recent"]["since"]
    for w in (q["all_time"], q["recent"]):
        assert w["cases_decided"] == w["human_reviewed"] == w["reclassifications"] == 0
        assert w["agreement_rate"] is None and w["escalation_rate"] is None and w["median_hours_to_final"] is None
        assert w["rules"] == w["transitions"] == w["reason_codes"] == []
        assert w["four_eyes"] == {"requested": 0, "approved": 0, "rejected": 0, "pending": 0}


def test_quality_metrics(client, auth, ruled):
    rv, sr = auth("reviewer"), auth("senior")
    a = new_case(client, auth, ruled, "APPROVE")                         # auto-approved, then overturned by a reviewer
    override(client, rv, a, "REJECT", "CONFIRMED_FRAUD")
    new_case(client, auth, ruled, "APPROVE")                             # auto-approved, never reviewed
    c = new_case(client, auth, ruled, "REJECT")                          # rejection confirmed by a reviewer
    override(client, rv, c, "REJECT", "CONFIRMED_AI_DECISION")
    d = new_case(client, auth, ruled, "ESCALATE")                        # escalation resolved below the four-eyes amount
    override(client, rv, d, "APPROVE", "DOCUMENT_VERIFIED_MANUALLY")
    e = new_case(client, auth, ruled, "ESCALATE", 25_000)                # four-eyes: approved
    ov = override(client, rv, e, "APPROVE", "FALSE_POSITIVE_FRAUD")
    assert client.post(f"/cases/{e}/overrides/{ov['id']}/approve", headers=sr).status_code == 200
    f = new_case(client, auth, ruled, "ESCALATE", 25_000)                # four-eyes: rejected, still in review
    ov = override(client, rv, f, "REJECT", "CONFIRMED_FRAUD")
    assert client.post(f"/cases/{f}/overrides/{ov['id']}/reject", json={"note": "not enough"}, headers=sr).status_code == 200
    g = new_case(client, auth, ruled, "ESCALATE", 25_000)                # four-eyes: pending
    override(client, rv, g, "APPROVE", "FALSE_POSITIVE_FRAUD")
    h = new_case(client, auth, ruled, "ESCALATE")                        # awaiting review, one document reclassified
    r = client.post(f"/cases/{h}/documents/doc0/reclassify", headers=rv,
                    json={"doc_type": "PRESCRIPTION", "reason_code": "CLASSIFICATION_ERROR"})
    assert r.status_code == 202
    age(a, timedelta(days=40))                                           # outside the 30-day cohort
    age(d, timedelta(hours=10))                                          # took ten hours to finalise

    q = client.get("/ops/quality", headers=auth("auditor")).json()
    w = q["all_time"]
    assert w["cases_decided"] == 8 and w["escalation_rate"] == 0.625
    assert (w["human_reviewed"], w["awaiting_review"], w["human_resolved"]) == (7, 3, 4)
    assert w["overrides_applied"] == 4 and w["applied_override_rate"] == 0.5
    assert w["agreement_rate"] == 0.25 and w["agreement_rate_approve_reject"] == 0.5
    assert [(x["reason_code"], x["requested"], x["applied"]) for x in w["reason_codes"]] == [
        ("CONFIRMED_FRAUD", 2, 1), ("FALSE_POSITIVE_FRAUD", 2, 1), ("CONFIRMED_AI_DECISION", 1, 1),
        ("DOCUMENT_VERIFIED_MANUALLY", 1, 1)]
    assert w["reason_codes"][0]["label"] == "Fraud signal confirmed"
    assert [(x["rule_id"], x["decision"], x["cases"], x["overridden"], x["changed"], x["change_rate"]) for x in w["rules"]] == [
        ("R3_fraud_or_low_confidence", "ESCALATE", 5, 2, 2, 0.4), ("R4_default", "APPROVE", 2, 1, 1, 0.5),
        ("R2_hard_failure", "REJECT", 1, 1, 0, 0.0)]
    assert {(x["ai_decision"], x["final_decision"]): x["cases"] for x in w["transitions"]} == {
        ("ESCALATE", "APPROVE"): 2, ("APPROVE", "REJECT"): 1, ("REJECT", "REJECT"): 1}
    assert w["confidence"] == {"confirmed": 0.9, "overridden": 0.65, "n_confirmed": 1, "n_overridden": 3}
    assert w["reclassifications"] == 1
    assert w["reclassification_types"] == [{"from_type": "CLAIM_FORM", "to_type": "PRESCRIPTION", "count": 1}]
    assert w["four_eyes"] == {"requested": 3, "approved": 1, "rejected": 1, "pending": 1}
    assert w["median_hours_to_final"] == pytest.approx(5.0, abs=0.1)            # median of ~960, ~10, ~0, ~0 hours

    rec = q["recent"]                                                    # case A left the cohort, with its override
    assert rec["cases_decided"] == 7 and rec["overrides_applied"] == 3 and rec["applied_override_rate"] == round(3 / 7, 4)
    assert rec["agreement_rate"] == round(1 / 3, 4) and rec["agreement_rate_approve_reject"] == 1.0
    assert ("APPROVE", "REJECT") not in {(x["ai_decision"], x["final_decision"]) for x in rec["transitions"]}
    assert next(x for x in rec["rules"] if x["rule_id"] == "R4_default")["changed"] == 0
    assert next(x for x in rec["reason_codes"] if x["reason_code"] == "CONFIRMED_FRAUD")["applied"] == 0
    assert rec["median_hours_to_final"] == pytest.approx(0.0, abs=0.1)
    assert rec["reclassifications"] == 1 and rec["four_eyes"]["requested"] == 3


def test_recent_window_follows_the_clock(client, auth, ruled):
    from medishield.db.repo import repo_scope
    from medishield.services.quality import compute_quality

    cid = new_case(client, auth, ruled, "APPROVE")
    override(client, auth("reviewer"), cid, "REJECT", "EXTRACTION_ERROR")
    with repo_scope() as db:
        later = compute_quality(db, now=datetime.now(UTC) + timedelta(days=31))
    assert later.all_time.cases_decided == 1 and later.all_time.agreement_rate == 0.0
    assert later.recent.cases_decided == 0 and later.recent.reason_codes == []


def test_repo_batch_reads_cover_every_case_and_override(env):
    """More rows than one DynamoDB batch (100 keys) returns, on both backends."""
    from medishield.db.models import Case, Override
    from medishield.db.repo import repo_scope

    with repo_scope() as db:
        for i in range(120):
            c = Case(id=f"CASE-Q{i:03d}", submitted_by="u", status="DECIDED", ai_decision="APPROVE",
                     decision={"decision": "APPROVE", "documents": [{"doc_id": "d0", "decision": "APPROVE", "rule_id": f"R{i}"}]})
            db.add_case(c)
            db.save_case(c)
            if i < 105:
                db.add_override(Override(case_id=c.id, requested_by="r", decision="REJECT", reason_code="OTHER",
                                         status="APPLIED" if i % 2 else "PENDING_APPROVAL"))
        db.commit()
    with repo_scope() as db:
        headers = db.case_headers()
        decisions = db.case_decisions([c.id for c in headers] + ["CASE-MISSING"])
        overrides = db.all_overrides()
    assert len(headers) == 120 and len(decisions) == 120
    assert decisions["CASE-Q007"]["documents"][0]["rule_id"] == "R7"
    assert len(overrides) == 105 and [o.id for o in overrides] == sorted(o.id for o in overrides)
    assert sum(o.status == "APPLIED" for o in overrides) == 52
