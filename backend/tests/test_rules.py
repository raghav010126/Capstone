"""Deterministic components: exclusion ranges, claims standard, fraud rules, grounding, schema conversion."""

from medishield.agents.claims import npi_luhn_ok, validate_claim, validate_rx
from medishield.agents.context import CaseContext, DocView
from medishield.decision.engine import load_policy
from medishield.fraud.rules import norm_claim_no, run_rules
from medishield.llm.client import strict_schema
from medishield.ocr.grounding import match_line
from medishield.rag.exclusions import CptRange, classify_row, lookup, parse_rows
from medishield.records import Records
from medishield.schemas import DocType, OcrLine
from medishield.schemas.llm_outputs import ClaimFormRead

# ── exclusion table ──────────────────────────────────────────────────────────────────────────────────
ROWS = [["15000-15999", "Integumentary / Skin Grafts (Cosmetic)", "Cosmetic S4(a)"],
        ["15820-15829", "Blepharoplasty - Eyelid Surgery", "Cosmetic S4(a)"],
        ["0001T-0099T", "Category III - Emerging Technologies", "Experimental S4(c)"],
        ["97010-97799", "Physical Medicine - Non-Acute", "Prior Auth Req S5"],
        ["99241-99245", "Outpatient Consultations (standalone)", "Specialist copay only"],
        ["V2100-V2799", "Spectacles / Eyeglasses / Contact Lenses", "Vision excl. S4(i)"],
        ["D0100-D9999", "Dental Procedures (ADA codes)", "Dental excl. S4(h)"]]
RANGES = parse_rows([["CPT Range", "Procedure Category", "Exclusion Basis"]] + ROWS, "gold")


def test_rows_classified_not_all_exclusions():
    assert classify_row("Physical Medicine - Non-Acute", "Prior Auth Req S5") == "prior_auth"
    assert classify_row("Outpatient Consultations", "Specialist copay only") == "copay_rule"
    assert [r.kind for r in RANGES].count("exclusion") == 5


def test_overlapping_ranges_both_match():
    assert {r.label for r in lookup("15822", RANGES)} == {"15000-15999", "15820-15829"}


def test_alphanumeric_families_do_not_cross():
    assert [r.label for r in lookup("0042T", RANGES)] == ["0001T-0099T"]
    assert lookup("0042", RANGES) == [] and lookup("00420", RANGES) == []
    assert [r.label for r in lookup("V2500", RANGES)] == ["V2100-V2799"]
    assert lookup("99213", RANGES) == [] and lookup("93000", RANGES) == []


def test_range_bounds_inclusive():
    r = CptRange("97010", "97799", "", "", "prior_auth", "gold")
    assert r.contains("97010") and r.contains("97799") and not r.contains("97800")


# ── claims standard ──────────────────────────────────────────────────────────────────────────────────
GOOD_CLAIM = {"patient_name": "Ann Lee", "patient_dob": "01/02/1980", "policy_number": "MED-GLD-1234567",
              "claim_number": "CLM-2024-00001", "service_date": "2025-11-09", "billing_provider": "Rush",
              "icd_codes": ["E11.9"], "provider_npi": "NPI-1029384756", "total_charge": 175.0,
              "service_lines": [{"cpt": "99213", "charge": 120.0}, {"cpt": "85025", "charge": 55.0}],
              "missing_markers": []}


def test_valid_claim_passes_and_npi_checksum_is_only_a_warning():
    errors, warnings, _ = validate_claim(GOOD_CLAIM)
    assert errors == []
    assert not npi_luhn_ok("1029384756") and any("checksum" in w for w in warnings)


def test_missing_marker_fails_standard():
    errors, _, _ = validate_claim({**GOOD_CLAIM, "missing_markers": ["auth_number"]})
    assert errors == ["form marks 'auth_number' as missing"]


def test_total_mismatch_is_warning_not_error():
    errors, warnings, _ = validate_claim({**GOOD_CLAIM, "total_charge": 9875.0})
    assert errors == [] and any(w.startswith("total_mismatch") for w in warnings)


def test_bad_codes_fail():
    errors, _, _ = validate_claim({**GOOD_CLAIM, "icd_codes": ["XYZ"], "service_lines": [{"cpt": "9921", "charge": 1}]})
    assert any("ICD-10" in e for e in errors) and any("cpt: invalid" in e for e in errors)


def test_rx_missing_drug_name_and_refills():
    rx = {"patient_name": "A", "rx_date": "2025-11-10", "prescriber": "Dr. X", "prescriber_npi": "NPI-1029384756",
          "dea_number": "BJ1029384", "drugs": [{"name": None, "sig": "1 tab daily"}],
          "refills_section_present": False, "missing_markers": []}
    errors, _, _ = validate_rx(rx)
    assert "drug 1: name missing" in errors and "refills: not specified" in errors


# ── fraud rules (one fixture per scenario) ───────────────────────────────────────────────────────────
MEMBER = {"member_id": "PT_1", "policy_number": "MED-GLD-1234567", "full_name": "Ann Lee", "dob": "1980-01-02",
          "status": "ACTIVE", "plan": "GOLD"}


def records() -> Records:
    return Records(members=[MEMBER], history=[])


def ctx(*docs) -> CaseContext:
    c = CaseContext("C_T")
    c.docs = [DocView(d, t, v, 0.95) for d, t, v in docs]
    return c


def codes(anoms):
    return {(a.code, a.doc_id) for a in anoms}


CFG = load_policy()["fraud"]


def test_readmission_within_30_days_flags_discharge():
    c = ctx(("claim", DocType.CLAIM_FORM, GOOD_CLAIM | {"service_date": "2025-12-15"}),
            ("dis", DocType.DISCHARGE_SUMMARY, {"admit_date": "2025-12-02", "discharge_date": "2025-12-05"}))
    assert ("readmission_30d", "dis") in codes(run_rules(c, records(), CFG)[0])


def test_same_stay_discharge_is_not_readmission():
    c = ctx(("claim", DocType.CLAIM_FORM, GOOD_CLAIM),
            ("dis", DocType.DISCHARGE_SUMMARY, {"admit_date": "2025-11-09", "discharge_date": "2025-11-12"}))
    assert not codes(run_rules(c, records(), CFG)[0])


def test_rx_far_after_service():
    c = ctx(("claim", DocType.CLAIM_FORM, GOOD_CLAIM), ("rx", DocType.PRESCRIPTION, {"rx_date": "2026-01-03"}))
    assert ("rx_date_after_service", "rx") in codes(run_rules(c, records(), CFG)[0])


def test_rx_two_days_after_service_is_fine():
    c = ctx(("claim", DocType.CLAIM_FORM, GOOD_CLAIM), ("rx", DocType.PRESCRIPTION, {"rx_date": "2025-11-11"}))
    assert not codes(run_rules(c, records(), CFG)[0])


def test_obstetric_code_without_pregnancy_dx():
    claim = GOOD_CLAIM | {"service_lines": [{"cpt": "59400", "charge": 3500.0}], "total_charge": 3500.0}
    assert ("obstetric_code_without_pregnancy_dx", "c") in codes(run_rules(ctx(("c", DocType.CLAIM_FORM, claim)), records(), CFG)[0])
    ok = claim | {"icd_codes": ["O80"]}
    assert not codes(run_rules(ctx(("c", DocType.CLAIM_FORM, ok)), records(), CFG)[0])


def test_structuring_band_with_combined_code():
    claim = GOOD_CLAIM | {"total_charge": 9875.0,
                          "service_lines": [{"cpt": "99213", "charge": 120.0}, {"cpt": "99999", "charge": 9875.0}]}
    assert ("structuring_below_10k", "c") in codes(run_rules(ctx(("c", DocType.CLAIM_FORM, claim)), records(), CFG)[0])


def test_duplicate_resubmission_flags_the_later_copy_only():
    c = ctx(("orig", DocType.CLAIM_FORM, GOOD_CLAIM),
            ("dup", DocType.CLAIM_FORM, GOOD_CLAIM | {"claim_number": "UB04-CLM-2024-00001"}))
    found = codes(run_rules(c, records(), CFG)[0])
    assert ("duplicate_claim", "dup") in found and ("duplicate_claim", "orig") not in found


def test_duplicate_across_cases_via_registry():
    r = records()
    _, new = run_rules(ctx(("first", DocType.CLAIM_FORM, GOOD_CLAIM)), r, CFG)
    for p in new:
        r.register(p)
    assert ("duplicate_claim", "again") in codes(run_rules(ctx(("again", DocType.CLAIM_FORM, GOOD_CLAIM)), r, CFG)[0])


def test_id_name_mismatch():
    c = ctx(("claim", DocType.CLAIM_FORM, GOOD_CLAIM), ("id", DocType.ID_DOCUMENT, {"name_on_id": "Bob Stone"}))
    assert ("identity_name_mismatch", "id") in codes(run_rules(c, records(), CFG)[0])


def test_claim_number_normalisation():
    assert norm_claim_no("UB04-CLM-2024-00004") == norm_claim_no("CLM-2024-00004") == "CLM202400004"


# ── grounding & schema ───────────────────────────────────────────────────────────────────────────────
def test_grounding_renderings():
    lines = [OcrLine(id=0, text="$1,250.00", box=(1, 2, 3, 4), score=0.99),
             OcrLine(id=1, text="Date of Service 12/15/2025", box=(5, 6, 7, 8), score=0.99),
             OcrLine(id=2, text="I10 Essential hypertension", box=(0, 0, 1, 1), score=0.99)]
    assert match_line(1250.0, lines)[:2] == (True, (1, 2, 3, 4))
    assert match_line("2025-12-15", lines)[0]
    assert match_line("I10", lines)[0] and not match_line("I11", lines)[0]


def test_strict_schema_requires_every_property_and_forbids_extras():
    s = strict_schema(ClaimFormRead)
    assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
    line = s["properties"]["service_lines"]["items"]
    assert line["additionalProperties"] is False and "$ref" not in str(s)


def test_same_layout_different_members_is_not_a_duplicate():
    other = {**MEMBER, "member_id": "PT_2", "policy_number": "MED-GLD-7654321", "full_name": "Bo Diaz"}
    r = Records(members=[MEMBER, other], history=[])
    c = CaseContext("C_T")
    c.docs = [DocView("a", DocType.CLAIM_FORM, GOOD_CLAIM, 0.95, image_hash="ffff0000ffff0000"),
              DocView("b", DocType.CLAIM_FORM, GOOD_CLAIM | {"policy_number": "MED-GLD-7654321",
                                                             "claim_number": "CLM-2024-00002",
                                                             "patient_name": "Bo Diaz"}, 0.95,
                      image_hash="ffff0000ffff0000")]
    assert not codes(run_rules(c, r, CFG)[0])


def test_tamper_needs_two_high_ratings():
    from medishield.agents.kyc import confirmed_tamper
    from medishield.schemas.llm_outputs import KycVisualRead

    def v(level):
        return KycVisualRead(tamper_indicators=["DOB in red"], layout_or_quality_issues=[], tamper_likelihood=level,
                             expired_marking=False, photo_present=True, assessment="")
    assert confirmed_tamper(v("high"), v("high"))
    assert not confirmed_tamper(v("medium"), v("high")) and not confirmed_tamper(v("medium"), v("medium"))
