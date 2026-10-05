"""Relational model. Large agent outputs are stored as JSON columns; everything the UI filters on is a column."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Timestamps are stored as UTC and always come back timezone-aware (SQLite drops the offset, which would make
    browsers read UTC times as local time)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict] = {dict[str, Any]: JSON, list[Any]: JSON}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    submitted_by: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="RECEIVED", index=True)
    # RECEIVED -> PROCESSING -> DECIDED (auto-final) | IN_REVIEW -> FINALIZED | FAILED
    ai_decision: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)     # CaseDecision dump
    fraud: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)        # FraudResult dump
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)   # LangGraph checkpoint thread
    wall_ms: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)            # spent in this run (0 when replayed from cache)
    cold_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)       # what the same calls cost without the cache
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    documents: Mapped[list[Document]] = relationship(back_populates="case", order_by="Document.position",
                                                     cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("submitted_by", "idempotency_key", name="uq_case_idempotency"),)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    doc_id: Mapped[str] = mapped_column(String(96))
    position: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    page: Mapped[int] = mapped_column(Integer, default=1)
    forced_type: Mapped[str | None] = mapped_column(String(32), nullable=True)   # set by a reclassification
    doc_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    classification: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    quality: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    specialists: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    image_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decision_detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    case: Mapped[Case] = relationship(back_populates="documents")
    __table_args__ = (UniqueConstraint("case_id", "doc_id", name="uq_case_doc"),)


class AgentRunRow(Base):
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    agent: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retried_with: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cold_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    cache_hits: Mapped[int] = mapped_column(Integer, default=0)


class CaseEvent(Base):
    """Pipeline progress events; the WebSocket/SSE endpoints stream rows with id > last seen."""
    __tablename__ = "case_events"
    __table_args__: ClassVar[dict] = {"sqlite_autoincrement": True}     # ids must never repeat: streaming clients keep a cursor on them
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(32), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    node: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    doc_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Override(Base):
    __tablename__ = "overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    requested_by: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str] = mapped_column(String(48))
    note: Mapped[str] = mapped_column(String(1000), default="")
    ai_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    requires_four_eyes: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING_APPROVAL")  # | APPLIED | REJECTED
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(48), index=True)
    case_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class PolicyDoc(Base):
    __tablename__ = "policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan: Mapped[str] = mapped_column(String(32), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_by: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="INGESTING")   # INGESTING | READY | FAILED
    product_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ranges: Mapped[list[Any]] = mapped_column(JSON, default=list)          # parsed table-4.1 rows
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
