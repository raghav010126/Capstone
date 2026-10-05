"""Run one case through the graph (used by the eval harness now, the API worker at checkpoint 3)."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from medishield.graph.build import build_graph
from medishield.ocr.engine import file_sha256
from medishield.schemas import DocumentInput

_graph = None


def graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_case(case_id: str, paths: list[tuple[str, str | Path]], records=None, store=None,
             hitl: bool = False) -> dict:
    """``paths``: [(doc_id, path)] in submission order. Returns the final graph state (plus wall time)."""
    docs = [DocumentInput(doc_id=d, case_id=case_id, path=str(p), sha256=file_sha256(p)).model_dump()
            for d, p in paths]
    config = {"configurable": {"thread_id": f"{case_id}-{uuid.uuid4().hex[:8]}", "records": records,
                               "store": store, "hitl": hitl}}
    t0 = time.perf_counter()
    state = graph().invoke({"case_id": case_id, "documents": docs}, config)
    state["wall_ms"] = (time.perf_counter() - t0) * 1000
    return state
