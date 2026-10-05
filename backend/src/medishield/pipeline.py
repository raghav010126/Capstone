"""Run a case through the LangGraph pipeline.

* ``run_case`` - blocking, used by the eval harness (in-memory checkpointer).
* ``run_case_stream`` / ``resume_case`` - used by the worker: events are pushed to a callback as each node
  finishes, and the graph's human-review interrupt is persisted in a SQLite checkpointer, so a reviewer can
  resume a paused case later (even after a restart).
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langgraph.types import Command

from medishield.config import get_settings
from medishield.graph.build import build_graph
from medishield.ocr.engine import file_sha256
from medishield.schemas import DocumentInput

_graph = None
_graph_persistent = None
_lock = threading.Lock()


def graph():
    """In-memory graph (eval harness)."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def persistent_graph():
    """Graph with a SQLite checkpointer (API worker)."""
    global _graph_persistent
    with _lock:
        if _graph_persistent is None:
            from langgraph.checkpoint.sqlite import SqliteSaver

            s = get_settings()
            s.state_dir.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(s.checkpoint_path), check_same_thread=False)
            _graph_persistent = build_graph(SqliteSaver(conn))
        return _graph_persistent


def reset_graphs() -> None:
    global _graph, _graph_persistent
    with _lock:
        _graph, _graph_persistent = None, None


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


def run_case_stream(case_id: str, paths: list[tuple[str, str | Path]], thread_id: str,
                    on_event: Callable[[dict], None], forced_types: dict[str, str] | None = None,
                    hitl: bool = True) -> dict[str, Any]:
    """Run to completion or to the human-review pause. Returns {values, paused, wall_ms}."""
    docs = [DocumentInput(doc_id=d, case_id=case_id, path=str(p), sha256=file_sha256(p)).model_dump()
            for d, p in paths]
    config = {"configurable": {"thread_id": thread_id, "hitl": hitl, "forced_types": forced_types or {}}}
    g = persistent_graph()
    t0 = time.perf_counter()
    for update in g.stream({"case_id": case_id, "documents": docs}, config, stream_mode="updates"):
        for node, payload in update.items():
            if node == "__interrupt__":
                on_event({"node": "human_review", "status": "waiting", "doc_id": None})
            elif isinstance(payload, dict):
                for ev in payload.get("events", []):
                    on_event(ev)
    snap = g.get_state(config)
    return {"values": dict(snap.values), "paused": "human_review" in (snap.next or ()),
            "wall_ms": (time.perf_counter() - t0) * 1000}


def resume_case(thread_id: str, resolution: dict, on_event: Callable[[dict], None]) -> dict[str, Any]:
    """Resume a paused case with the reviewer's resolution."""
    g = persistent_graph()
    config = {"configurable": {"thread_id": thread_id}}
    for update in g.stream(Command(resume=resolution), config, stream_mode="updates"):
        for payload in update.values():
            if isinstance(payload, dict):
                for ev in payload.get("events", []):
                    on_event(ev)
    snap = g.get_state(config)
    return {"values": dict(snap.values), "paused": "human_review" in (snap.next or ())}
