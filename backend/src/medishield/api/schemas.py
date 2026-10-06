"""API request/response models (the OpenAPI schema the Next.js client is generated from)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from medishield.schemas import (
    CaseDecision,
    ClaimsResult,
    Classification,
    DocumentDecision,
    ExtractedField,
    FraudResult,
    KycResult,
    PolicyResult,
    QualityMetrics,
)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    display_name: str


class UserOut(BaseModel):
    username: str
    display_name: str
    role: str
    permissions: list[str] = []


class CaseSummary(BaseModel):
    id: str
    status: str
    display_status: str
    ai_decision: str | None
    final_decision: str | None
    confidence: float | None
    risk_score: float
    total_amount: float
    n_documents: int
    submitted_by: str
    created_at: datetime
    sla_due: datetime
    sla_breached: bool
    pending_override: bool = False
    error: str | None = None


class DocumentOut(BaseModel):
    doc_id: str
    filename: str
    position: int
    media_type: str
    doc_type: str | None
    classification: Classification | None = None
    quality: QualityMetrics | None = None
    fields: list[ExtractedField] = []
    grounding_rate: float | None = None
    confidence: float | None = None
    kyc: KycResult | None = None
    claims: ClaimsResult | None = None
    policy: PolicyResult | None = None
    decision: DocumentDecision | None = None
    image_url: str
    forced_type: str | None = None


class AgentRunOut(BaseModel):
    agent: str
    model: str | None
    retried_with: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cold_cost_usd: float = 0.0
    latency_ms: float
    llm_calls: int


class OverrideOut(BaseModel):
    id: int
    case_id: str
    requested_by: str
    decision: str
    reason_code: str
    note: str
    ai_decision: str | None
    amount: float
    requires_four_eyes: bool
    status: str
    resolved_by: str | None
    created_at: datetime
    resolved_at: datetime | None


class CaseDetail(CaseSummary):
    decision: CaseDecision | None
    fraud: FraudResult | None
    documents: list[DocumentOut]
    agent_runs: list[AgentRunOut]
    overrides: list[OverrideOut]
    wall_ms: float
    cost_usd: float
    cold_cost_usd: float = 0.0
    warnings: list[str] = []


class UploadMode(BaseModel):
    mode: str                       # "direct" (multipart to the API) | "presigned" (browser -> S3, then /cases/from-uploads)
    max_file_bytes: int
    max_files: int


class UploadFileSpec(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)


class UploadRequest(BaseModel):
    files: list[UploadFileSpec] = Field(min_length=1)


class UploadTarget(BaseModel):
    url: str
    fields: dict[str, str]
    key: str


class UploadGrant(BaseModel):
    upload_id: str
    uploads: list[UploadTarget]


class FromUploads(BaseModel):
    upload_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class CaseCreated(BaseModel):
    case_id: str
    status: str
    documents: list[str]
    warnings: list[str] = []
    idempotent_replay: bool = False


class EventOut(BaseModel):
    id: int
    ts: datetime
    node: str
    status: str
    doc_id: str | None
    payload: dict[str, Any] = {}


class OverrideRequest(BaseModel):
    decision: str
    reason_code: str
    note: str = Field(default="", max_length=1000)


class DecisionNote(BaseModel):
    note: str = Field(default="", max_length=300)


class ReclassifyRequest(BaseModel):
    doc_type: str
    reason_code: str
    note: str = Field(default="", max_length=1000)


class AuditOut(BaseModel):
    seq: int
    ts: str
    actor: str
    action: str
    case_id: str | None
    detail: dict[str, Any]
    prev_hash: str
    hash: str


class ChainStatus(BaseModel):
    ok: bool
    length: int
    broken_at: int | None
    reason: str | None
    head: str | None = None


class PolicyOut(BaseModel):
    id: int
    plan: str
    filename: str
    status: str
    product_code: str | None
    chunk_count: int
    exclusion_rows: int
    uploaded_by: str
    error: str | None
    created_at: datetime


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,100}$")


class ChatSource(BaseModel):
    n: int
    kind: str
    title: str
    url: str | None = None
    page: int | None = None
    cited: bool = False


class ChatResponse(BaseModel):
    answer: str
    route: str
    blocked: bool
    role: str
    conversation_id: str
    router: str = ""
    sql: str | None = None
    sources: list[ChatSource] = []
    accessible: list[str] = []
    restricted: list[str] = []


class ChatSourceInfo(BaseModel):
    id: str
    label: str


class ChatScope(BaseModel):
    role: str
    accessible: list[ChatSourceInfo]
    restricted: list[ChatSourceInfo]
    examples: list[str]


class CaseProgress(BaseModel):
    events: list[EventOut]
    status: str
