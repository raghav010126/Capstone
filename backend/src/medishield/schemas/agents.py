"""Typed contracts between agents. Field names follow the assignment brief; extra fields carry evidence."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from medishield.schemas.common import Box, CoverageStatus, Decision, DocType, RiskLevel, Strict


# ── Pre-processing ────────────────────────────────────────────────────────────────────────────────────
class OcrLine(Strict):
    id: int
    text: str
    box: Box
    score: float


class QualityMetrics(Strict):
    width: int
    height: int
    sharpness: float = Field(description="variance of the Laplacian on a normalised-size greyscale image")
    blank: bool
    blur_suspected: bool
    ocr_mean_score: float
    ocr_lines: int
    quality_score: float = Field(description="0-1 evidence score combining sharpness and OCR confidence")


class DocumentInput(Strict):
    doc_id: str
    case_id: str
    path: str
    sha256: str = ""


# ── Classifier ────────────────────────────────────────────────────────────────────────────────────────
class Classification(Strict):
    doc_type: DocType
    confidence: float = Field(description="evidence-based (LLM/keyword agreement x image quality)")
    routing_tags: list[str]
    llm_doc_type: DocType
    llm_self_confidence: float = Field(description="model's self-report; audit only")
    keyword_doc_type: DocType | None
    keyword_margin: float
    reason: str
    language: str = Field(default="en", description="detected script/language of the page: en, es, hi")


# ── OCR / extraction ──────────────────────────────────────────────────────────────────────────────────
class ExtractedField(Strict):
    name: str
    value: Any
    grounded: bool = Field(description="value fuzzy-matches OCR text on the page")
    box: Box | None = None
    match_score: float = 0.0
    corroborated: bool = Field(default=False, description="value matches the system of record "
                                                          "(member DB) even if OCR could not read it")

    @property
    def supported(self) -> bool:
        return self.grounded or self.corroborated


class ExtractionResult(Strict):
    """Brief shape: ``{fields: [...], raw_text, bounding_boxes}`` plus grounding evidence."""
    doc_type: DocType
    fields: list[ExtractedField]
    values: dict[str, Any] = Field(description="the full typed reading (llm_outputs.*Read) as a dict")
    raw_text: str
    bounding_boxes: list[OcrLine]
    grounding_rate: float = Field(description="share of non-empty scalar fields grounded in OCR")
    support_rate: float = Field(description="share grounded OR corroborated by the system of record")
    confidence: float


# ── Specialist agents ─────────────────────────────────────────────────────────────────────────────────
class Check(Strict):
    name: str
    passed: bool | None = Field(description="None = could not be evaluated")
    detail: str = ""


class KycResult(Strict):
    kyc_passed: bool
    flags: list[str] = Field(description="hard findings, e.g. 'expired_id', 'member_not_found', 'tamper_suspected'")
    warnings: list[str] = Field(default_factory=list, description="informational, e.g. 'expiring_soon_id'")
    confidence: float
    member_id: str | None = None
    reference_date: str | None = Field(default=None, description="date of service used for expiry checks")
    checks: list[Check] = Field(default_factory=list)
    forensics: dict[str, Any] = Field(default_factory=dict, description="ELA / typography findings (evidence for reviewers)")


class ClaimsResult(Strict):
    extracted_fields: dict[str, Any]
    schema_valid: bool
    validation_errors: list[str]
    warnings: list[str] = Field(default_factory=list)
    confidence: float


class RetrievedChunk(Strict):
    query_code: str
    rank: int
    chunk_id: str
    plan: str
    section: str
    page: int | None
    score: float
    text: str


class CodeCoverage(Strict):
    code: str
    description: str | None = None
    status: CoverageStatus
    matched_range: str | None = None
    exclusion_basis: str | None = None
    benefit_category: str | None = None
    coverage_percentage: float | None = None
    citation: str | None = None


class PolicyResult(Strict):
    covered: bool
    coverage_status: CoverageStatus
    coverage_percentage: float | None
    policy_clause: str
    exclusions: list[str]
    per_code: list[CodeCoverage]
    plan: str | None
    retrieved: list[RetrievedChunk] = Field(default_factory=list)
    confidence: float
    rationale: str = ""


class FraudAnomaly(Strict):
    code: str
    doc_id: str
    weight: float
    detail: str
    source: str = Field(description="'rule' or 'llm'")


class FraudResult(Strict):
    fraud_score: float = Field(description="case-level score = max per-document score")
    per_doc_score: dict[str, float]
    anomalies: list[FraudAnomaly]
    risk_level: RiskLevel
    narrative: str = ""


# ── Orchestrator ──────────────────────────────────────────────────────────────────────────────────────
class DocumentDecision(Strict):
    doc_id: str
    doc_type: DocType
    decision: Decision
    confidence: float
    rule_id: str
    reasons: list[str]
    justification: str = ""


class CaseDecision(Strict):
    case_id: str
    decision: Decision
    confidence: float
    documents: list[DocumentDecision]
    agent_summaries: dict[str, str]
    justification: str
