"""LangGraph case state. Values are JSON-able dicts (pydantic ``model_dump``) so any checkpointer can persist
them; parallel branches write disjoint keys and are merged by the reducers."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge(a: dict, b: dict) -> dict:
    return {**(a or {}), **(b or {})}


class CaseState(TypedDict, total=False):
    case_id: str
    documents: list[dict]                                  # DocumentInput dumps, submission order
    perception: Annotated[dict[str, dict], merge]          # doc_id -> {quality, classification, extraction, ...}
    specialists: Annotated[dict[str, dict], merge]         # doc_id -> {kyc, claims, policy, failed}
    fraud: dict
    decision: dict
    review: dict                                           # human-in-the-loop resolution, if any
    runs: Annotated[list[dict], operator.add]              # AgentRun dumps (telemetry)
    events: Annotated[list[dict], operator.add]            # status events (streamed to the UI at checkpoint 3)


class DocTask(TypedDict):
    """Payload of a ``Send`` to a per-document node."""
    case_id: str
    doc: dict
    perception: dict[str, Any]
    documents: list[dict]
