"""Claims agent: validates extracted claim data against MediShield's claim submission standard.

Deterministic rules only (the LLM already did the reading):
* required fields present; anything the form itself prints as [MISSING]/[ILLEGIBLE] fails the standard;
* ICD-10 and CPT/HCPCS code formats; NPI format (10 digits; the Luhn checksum is logged as a warning only,
  because every provider NPI in the dataset fails it - finding F15);
* total = sum of line charges. A mismatch is a *warning* and a fraud signal (structuring), not a schema error.
Discharge summaries and prescriptions get a lighter rule set ("claims-lite").
"""

from __future__ import annotations

import re

from medishield.records import parse_date
from medishield.schemas import ClaimsResult, DocType, ExtractionResult

ICD10 = re.compile(r"^[A-TV-Z][0-9][0-9AB](\.[0-9A-TV-Z]{1,4})?$")
CPT = re.compile(r"^(\d{4}[0-9FTU]|[A-V]\d{4})$")
NPI = re.compile(r"^(NPI-?)?(\d{10})$")
DEA = re.compile(r"^[A-Z]{2}\d{7}$")
UNLISTED_CPT = {"99999", "99499", "99199"}


def npi_luhn_ok(npi10: str) -> bool:
    digits = [int(c) for c in "80840" + npi10]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return total % 10 == 0


def _npi(value: str | None, errors: list[str], warnings: list[str], label: str) -> None:
    if not value:
        errors.append(f"{label}: missing")
        return
    m = NPI.match(value.replace(" ", ""))
    if not m:
        errors.append(f"{label}: invalid format {value!r}")
    elif not npi_luhn_ok(m.group(2)):
        warnings.append(f"{label}: checksum fails (format accepted)")


def validate_claim(v: dict) -> tuple[list[str], list[str], dict]:
    errors: list[str] = []
    warnings: list[str] = []
    for f in ("patient_name", "patient_dob", "policy_number", "claim_number", "service_date",
              "billing_provider"):
        if not v.get(f):
            errors.append(f"{f}: missing")
    if v.get("service_date") and not parse_date(v["service_date"]):
        errors.append(f"service_date: unparseable {v['service_date']!r}")
    for m in v.get("missing_markers") or []:
        errors.append(f"form marks '{m}' as missing")
    icds = [i.strip().upper() for i in v.get("icd_codes") or [] if i]
    if not icds:
        errors.append("icd_codes: none")
    for i in icds:
        if not ICD10.match(i):
            errors.append(f"icd_codes: invalid ICD-10 {i!r}")
    lines = v.get("service_lines") or []
    cpts = [ln["cpt"].strip().upper() for ln in lines if ln.get("cpt")]
    if not cpts:
        errors.append("service_lines: no CPT/HCPCS codes")
    for c in cpts:
        if not CPT.match(c):
            errors.append(f"cpt: invalid code {c!r}")
        elif c in UNLISTED_CPT:
            warnings.append(f"cpt: unlisted/combined code {c}")
    _npi(v.get("provider_npi"), errors, warnings, "provider_npi")
    charges = [ln["charge"] for ln in lines if ln.get("charge") is not None]
    total = v.get("total_charge")
    if total is None:
        errors.append("total_charge: missing")
    elif charges and abs(sum(charges) - total) > 0.01:
        warnings.append(f"total_mismatch: lines sum {sum(charges):.2f} != total {total:.2f}")
    fields = {"form_type": v.get("form_type"), "claim_number": v.get("claim_number"),
              "service_date": v.get("service_date"), "icd_codes": icds, "cpt_codes": cpts,
              "line_charges": charges, "total_charge": total, "provider_npi": v.get("provider_npi"),
              "billing_provider": v.get("billing_provider"), "attending_physician": v.get("attending_physician")}
    return errors, warnings, fields


def validate_discharge(v: dict) -> tuple[list[str], list[str], dict]:
    errors, warnings = [], []
    for f in ("patient_name", "admit_date", "discharge_date", "primary_icd"):
        if not v.get(f):
            errors.append(f"{f}: missing")
    a, d = parse_date(v.get("admit_date")), parse_date(v.get("discharge_date"))
    if a and d and d < a:
        errors.append("discharge_date before admit_date")
    if v.get("primary_icd") and not ICD10.match(v["primary_icd"].strip().upper()):
        warnings.append(f"primary_icd: unusual format {v['primary_icd']!r}")
    return errors, warnings, {k: v.get(k) for k in ("admit_date", "discharge_date", "primary_icd", "cpt_codes")}


def validate_rx(v: dict) -> tuple[list[str], list[str], dict]:
    errors, warnings = [], []
    for f in ("patient_name", "rx_date", "prescriber"):
        if not v.get(f):
            errors.append(f"{f}: missing")
    _npi(v.get("prescriber_npi"), errors, warnings, "prescriber_npi")
    dea = (v.get("dea_number") or "").replace(" ", "")
    if not dea:
        errors.append("dea_number: missing")
    elif not DEA.match(dea):
        errors.append(f"dea_number: invalid format {dea!r}")
    drugs = v.get("drugs") or []
    if not drugs:
        errors.append("drugs: none prescribed")
    for i, d in enumerate(drugs, 1):
        if not d.get("name"):
            errors.append(f"drug {i}: name missing")
        if not d.get("sig"):
            errors.append(f"drug {i}: dosage/sig missing")
    if not v.get("refills_section_present", True):
        errors.append("refills: not specified")
    for m in v.get("missing_markers") or []:
        errors.append(f"form marks '{m}' as missing")
    return errors, warnings, {"rx_date": v.get("rx_date"), "prescriber_npi": v.get("prescriber_npi"),
                              "dea_number": v.get("dea_number"), "drugs": [d.get("name") for d in drugs]}


VALIDATORS = {DocType.CLAIM_FORM: validate_claim, DocType.DISCHARGE_SUMMARY: validate_discharge,
              DocType.PRESCRIPTION: validate_rx}


def run_claims(doc_type: DocType, ext: ExtractionResult) -> ClaimsResult:
    errors, warnings, fields = VALIDATORS[doc_type](ext.values)
    errors = list(dict.fromkeys(errors))
    return ClaimsResult(extracted_fields=fields, schema_valid=not errors, validation_errors=errors,
                        warnings=warnings, confidence=ext.confidence)
