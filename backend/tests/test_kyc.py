"""KYC judges ID validity on the date of service (finding F11), not today. The vision call is stubbed."""

import pytest
from medishield.agents import kyc
from medishield.agents.context import CaseContext, DocView
from medishield.records import Records
from medishield.schemas import AgentRun, DocType, ExtractionResult
from medishield.schemas.llm_outputs import KycVisualRead

MEMBER = {"member_id": "PT_1", "policy_number": "MED-GLD-1234567", "full_name": "Ann Lee", "dob": "1980-01-02",
          "status": "ACTIVE", "plan": "GOLD"}


@pytest.fixture(autouse=True)
def no_vision(monkeypatch):
    clean = KycVisualRead(tamper_indicators=[], layout_or_quality_issues=[], tamper_likelihood="none",
                          expired_marking=False, photo_present=True, assessment="ok")
    monkeypatch.setattr(kyc, "_visual", lambda path, tag: (clean, [], AgentRun(agent="kyc_visual")))


def run(expiry: str | None, dos: str = "2025-11-09", stamps=()):
    ext = ExtractionResult(doc_type=DocType.ID_DOCUMENT, fields=[], raw_text="", bounding_boxes=[],
                           grounding_rate=1, support_rate=1, confidence=0.95,
                           values={"name_on_id": "ANN LEE", "dob": "01/02/1980", "expiry_date": expiry,
                                   "policy_number": None, "stamps": list(stamps)})
    ctx = CaseContext("C", [DocView("claim", DocType.CLAIM_FORM, {"service_date": dos, "patient_name": "Ann Lee",
                                                                     "patient_dob": "01/02/1980",
                                                                     "policy_number": "MED-GLD-1234567"}, 0.95)])
    res, _ = kyc.verify_id("id", "unused.png", ext, ctx, Records([MEMBER], []))
    return res


def test_valid_on_date_of_service_even_if_expired_today():
    res = run("2026-03-01", dos="2025-11-09")          # expired relative to Oct 2026, valid on the DOS
    assert res.kyc_passed and res.reference_date == "2025-11-09" and "expiring_soon_id" not in res.warnings


def test_expired_before_service_fails():
    res = run("2025-10-01")
    assert not res.kyc_passed and "expired_id" in res.flags


def test_expiring_soon_is_warning_only():
    res = run("2025-11-25")
    assert res.kyc_passed and "expiring_soon_id" in res.warnings


def test_no_expiry_date_uses_stamp():
    assert "expired_id" in run(None, stamps=["CARD EXPIRED"]).flags
    res = run(None)
    assert res.kyc_passed and res.confidence <= 0.85     # cannot verify validity -> less confident


def test_member_found_via_case_when_id_has_no_policy():
    res = run("2029-01-01")
    assert res.member_id == "PT_1"
