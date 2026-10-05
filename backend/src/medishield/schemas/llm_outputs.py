"""What the perception LLM is asked to return, per document type.

These are *readings* of the document, never judgements: the model transcribes what is printed (or marked as
missing) and the deterministic agents decide what it means. Dates the model normalises are ISO
``YYYY-MM-DD``; dates of birth stay exactly as printed (``MM/DD/YYYY``) so they can be grounded verbatim.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from medishield.schemas.common import DocType, Strict


class ClassifierOutput(Strict):
    doc_type: DocType
    confidence: float = Field(description="0-1 self-reported; logged for audit, not used to decide")
    routing_tags: list[str] = Field(description="short tags, e.g. 'cms1500', 'ub04', 'handwritten', "
                                                "'blurry', 'has_attached_id', 'non_medical'")
    reason: str = Field(description="one sentence: which visual/text cues identify the type")


class ServiceLine(Strict):
    cpt: str | None = Field(description="CPT/HCPCS code exactly as printed, or null for revenue-code-only lines")
    revenue_code: str | None = None
    description: str | None = None
    charge: float | None = None


class ClaimFormRead(Strict):
    form_type: Literal["CMS1500", "UB04", "OTHER"]
    patient_name: str | None
    patient_dob: str | None = Field(description="as printed, MM/DD/YYYY")
    policy_number: str | None
    claim_number: str | None
    service_date: str | None = Field(description="date of service on the service lines, YYYY-MM-DD")
    admission_date: str | None = None
    discharge_date: str | None = None
    icd_codes: list[str]
    service_lines: list[ServiceLine] = Field(description="every charge line, including room & board lines")
    total_charge: float | None
    provider_npi: str | None = Field(description="as printed, e.g. NPI-1234567890")
    billing_provider: str | None
    attending_physician: str | None
    prior_auth_number: str | None = None
    missing_markers: list[str] = Field(description="fields printed as [MISSING]/[ILLEGIBLE]/'MISSING', "
                                                   "named e.g. 'dob', 'npi', 'diag_code', 'auth_number'")


class IdDocumentRead(Strict):
    id_type: Literal["drivers_license", "passport", "state_id", "insurance_card", "medicare_card", "other"]
    name_on_id: str | None
    dob: str | None = Field(description="as printed, MM/DD/YYYY")
    expiry_date: str | None = Field(description="YYYY-MM-DD, or null if no expiry date is printed")
    policy_number: str | None
    id_number: str | None
    stamps: list[str] = Field(description="overlaid stamps/warnings, e.g. 'EXPIRED', 'VOID', 'CARD EXPIRED'")


class DischargeRead(Strict):
    patient_name: str | None
    patient_dob: str | None = Field(description="as printed, MM/DD/YYYY")
    admit_date: str | None = Field(description="YYYY-MM-DD")
    discharge_date: str | None = Field(description="YYYY-MM-DD")
    primary_icd: str | None
    secondary_icds: list[str]
    cpt_codes: list[str]
    attending_physician: str | None
    provider_npi: str | None
    facility: str | None


class RxDrug(Strict):
    name: str | None = Field(description="generic drug name; null if printed as missing")
    brand: str | None = None
    sig: str | None = Field(description="dosage instructions; null if illegible/missing")
    quantity: str | None = None


class PrescriptionRead(Strict):
    patient_name: str | None
    patient_dob: str | None = Field(description="as printed, MM/DD/YYYY")
    rx_date: str | None = Field(description="YYYY-MM-DD")
    prescriber: str | None
    prescriber_npi: str | None
    dea_number: str | None = Field(description="null if absent or printed as [MISSING]")
    drugs: list[RxDrug]
    refills_section_present: bool = Field(description="is a 'Refills' row/section printed at all?")
    missing_markers: list[str] = Field(description="items printed as [MISSING]/[ILLEGIBLE], e.g. "
                                                   "'dea', 'dosage', 'drug_name'")
    stamps: list[str] = Field(description="red warnings/stamps printed on the form, verbatim")


class AmendmentRead(Strict):
    policy_number: str | None
    policyholder: str | None
    dob: str | None = Field(description="as printed, MM/DD/YYYY")
    group_number: str | None
    amendment_type: str | None = Field(description="the selected/checked amendment type")
    effective_date: str | None = Field(description="YYYY-MM-DD")
    signed: bool
    handwritten: bool = Field(description="are the filled-in values handwritten?")
    attached_id_present: bool = Field(description="is an identity document attached/pasted below the form?")
    attached_id_name: str | None = None
    attached_id_expiry: str | None = Field(default=None, description="YYYY-MM-DD")


class KycVisualRead(Strict):
    """KYC agent's own visual inspection of an identity document."""
    tamper_indicators: list[str] = Field(description="evidence of LOCALISED ALTERATION of the card's content: "
                                                     "a value whose font/size/ink differs from its neighbours, "
                                                     "overwritten or pasted-over characters, a patch with a "
                                                     "different background. Empty if none.")
    layout_or_quality_issues: list[str] = Field(description="design/rendering/scan problems that are not "
                                                            "alterations: overlapping bands, clipped text, "
                                                            "placeholder photos, simplified or non-standard "
                                                            "MRZ, blur, low resolution")
    tamper_likelihood: Literal["none", "low", "medium", "high"]
    expired_marking: bool = Field(description="an EXPIRED/VOID stamp or red expiry warning is printed")
    photo_present: bool
    assessment: str = Field(description="one sentence")


READ_MODELS: dict[DocType, type[Strict]] = {
    DocType.CLAIM_FORM: ClaimFormRead,
    DocType.ID_DOCUMENT: IdDocumentRead,
    DocType.DISCHARGE_SUMMARY: DischargeRead,
    DocType.PRESCRIPTION: PrescriptionRead,
    DocType.POLICY_AMENDMENT: AmendmentRead,
}


class PolicyCodeRead(Strict):
    code: str
    benefit_category: str | None = Field(description="exact 'Benefit Category' row name from the Schedule of "
                                                     "Benefits that applies, or null if none applies")
    coverage_status: Literal["COVERED", "NOT_COVERED", "CONDITIONAL"]
    conditions: list[str] = Field(description="unmet conditions, e.g. 'requires Maternity Rider', "
                                              "'prior authorization required'")
    citation_section: str = Field(description="section number and title relied on, e.g. '3. Inclusions'")
    citation_page: int | None
    rationale: str = Field(description="one or two sentences grounded in the quoted policy text")


class PolicyRead(Strict):
    codes: list[PolicyCodeRead]
    summary: str


class FraudLLMAnomaly(Strict):
    doc_id: str
    code: str = Field(description="short snake_case label")
    detail: str
    severity: Literal["low", "medium"]


class FraudRead(Strict):
    narrative: str = Field(description="3-5 sentences for the human reviewer, citing the documents")
    additional_anomalies: list[FraudLLMAnomaly] = Field(description="cross-document inconsistencies NOT "
                                                                    "already listed by the rules; empty if none")


class DocJustification(Strict):
    doc_id: str
    justification: str


class JustificationRead(Strict):
    case_justification: str
    documents: list[DocJustification]
