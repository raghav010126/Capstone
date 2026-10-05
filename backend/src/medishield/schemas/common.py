"""Shared enums and small value types."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DocType(StrEnum):
    CLAIM_FORM = "CLAIM_FORM"
    ID_DOCUMENT = "ID_DOCUMENT"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    PRESCRIPTION = "PRESCRIPTION"
    POLICY_AMENDMENT = "POLICY_AMENDMENT"
    UNKNOWN = "UNKNOWN"


class Decision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CoverageStatus(StrEnum):
    COVERED = "COVERED"
    NOT_COVERED = "NOT_COVERED"        # inside an exclusion range: automatic denial per policy 4.1
    CONDITIONAL = "CONDITIONAL"        # needs a rider / prior authorisation we cannot confirm -> review


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Box = tuple[int, int, int, int]       # x0, y0, x1, y1 in original image pixels


class AgentRun(Strict):
    """Telemetry for one agent step (one or more LLM calls, or none for deterministic agents)."""
    agent: str
    model: str | None = None
    retried_with: str | None = None    # set when the step escalated to the retry model
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0              # spent in this run (0 when served from the response cache)
    cold_cost_usd: float = 0.0         # cost of the same calls without the cache
    latency_ms: float = 0.0
    llm_calls: int = 0
    cache_hits: int = 0
