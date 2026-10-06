"""LangSmith tracing with PHI scrubbing.

Every case becomes one trace: the LangGraph run (one span per node) with a child span for each model call, carrying
model, effort, token usage, cost, latency and whether the answer came from the response cache.

Nothing identifying leaves the process. A ``hide_inputs`` / ``hide_outputs`` scrubber runs on every span *before* it is
sent: page images are dropped, OCR text is replaced by its length, identity fields are masked by name, and every remaining
string passes the same PHI redactor used for logs. Tracing is off unless ``LANGSMITH_API_KEY`` is set (and
``MEDISHIELD_TRACING`` is not ``0``).
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from medishield.phi import redact

log = logging.getLogger(__name__)

# Fields that identify a person, a policy or a provider: masked wherever they appear as a key.
SENSITIVE_KEYS = {
    "patient_name", "name_on_id", "policyholder", "attached_id_name", "attending_physician", "prescriber", "facility",
    "billing_provider", "patient_dob", "dob", "policy_number", "group_number", "claim_number", "provider_npi",
    "prescriber_npi", "dea_number", "id_number", "address", "member_id", "full_name", "ssn",
}
DROP_KEYS = {"raw_text", "bounding_boxes", "data_b64", "image", "ocr_lines"}
_OCR_BLOCK = re.compile(r"<ocr>.*?</ocr>", re.DOTALL)
# identity fields serialised inside a string (e.g. a case summary embedded in a prompt as JSON): "patient_name": "..."
_KV = re.compile(r"""(["'](?:""" + "|".join(sorted(SENSITIVE_KEYS)) + r""")["']\s*:\s*)(?:"[^"]*"|'[^']*'|\[[^\]]*\])""")


def scrub(obj: Any, key: str = "") -> Any:
    """Return a copy of ``obj`` that is safe to send to a third-party observability service."""
    if key in DROP_KEYS:
        n = len(obj) if hasattr(obj, "__len__") else 0
        return f"[omitted: {n}]"
    if key in SENSITIVE_KEYS and obj not in (None, "", [], {}):
        return "[REDACTED]"
    if isinstance(obj, dict):
        if obj.get("type") == "image" or ("source" in obj and isinstance(obj.get("source"), dict) and "data" in obj["source"]):
            return {"type": "image", "note": "[image omitted]"}
        # an extracted field is {"name": "patient_name", "value": ...}: the sensitivity is in the name, not the key
        if str(obj.get("name", "")).split("[")[0].split(".")[-1] in SENSITIVE_KEYS and "value" in obj:
            return {**{k: scrub(v, str(k)) for k, v in obj.items() if k != "value"}, "value": "[REDACTED]"}
        return {k: scrub(v, str(k)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v, key) for v in obj]
    if isinstance(obj, str):
        text = _OCR_BLOCK.sub(lambda m: f"<ocr>[OCR text omitted: {len(m.group(0))} chars]</ocr>", obj)
        text = _KV.sub(lambda m: f'{m.group(1)}"[REDACTED]"', text)
        return redact(text)[:6000]
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    return redact(str(obj))[:500]


@lru_cache
def _client():
    """The LangSmith client, or None when tracing is not configured."""
    if os.environ.get("MEDISHIELD_TRACING", "1") == "0" or not os.environ.get("LANGSMITH_API_KEY"):
        return None
    from langsmith import Client

    return Client(hide_inputs=scrub, hide_outputs=scrub)


def project() -> str:
    return os.environ.get("LANGSMITH_PROJECT", "medishield-capstone")


def enabled() -> bool:
    return _client() is not None


def graph_config(case_id: str, extra_tags: list[str] | None = None) -> dict:
    """Extra LangGraph run config that attaches our scrubbing tracer (and nothing else) to this run."""
    c = _client()
    if c is None:
        return {}
    from langchain_core.tracers.langchain import LangChainTracer

    return {"callbacks": [LangChainTracer(client=c, project_name=project())], "run_name": "case",
            "tags": ["medishield", *(extra_tags or [])], "metadata": {"case_ref": case_id}}


@contextmanager
def llm_span(step: str, model: str, effort: str, inputs: dict):
    """Context manager around one model call; yields a callable ``finish(outputs, **metadata)``."""
    c = _client()
    if c is None:
        yield lambda outputs=None, **meta: None
        return
    from langsmith import trace, tracing_context

    with tracing_context(enabled=True, client=c, project_name=project()), \
            trace(name=f"llm:{step}", run_type="llm", inputs=inputs, client=c, project_name=project(),
                  metadata={"ls_provider": "anthropic", "ls_model_name": model, "effort": effort, "step": step}) as rt:
        def finish(outputs: dict | None = None, **meta: Any) -> None:
            if meta:
                rt.add_metadata(meta)
            if outputs is not None:
                rt.end(outputs=outputs)

        yield finish


@contextmanager
def root_span(name: str, inputs: dict, tags: list[str] | None = None, metadata: dict | None = None):
    """A top-level trace (e.g. one assistant question); model calls inside it nest under it. Flushed on exit, because the
    process (an AgentCore microVM) may be paused right after it answers."""
    c = _client()
    if c is None:
        yield lambda outputs=None, **meta: None
        return
    from langsmith import trace, tracing_context

    # langsmith's trace() is a no-op unless tracing is switched on; enable it for this block only (not process-wide)
    with tracing_context(enabled=True, client=c, project_name=project()), \
            trace(name=name, run_type="chain", inputs=inputs, client=c, project_name=project(),
                  tags=["medishield", *(tags or [])], metadata=metadata or {}) as rt:
        def finish(outputs: dict | None = None, **meta: Any) -> None:
            if meta:
                rt.add_metadata(meta)
            if outputs is not None:
                rt.end(outputs=outputs)

        yield finish
    flush()


def flush() -> None:
    c = _client()
    if c is not None:
        try:
            c.flush()
        except Exception:
            log.warning("could not flush LangSmith traces", exc_info=True)
