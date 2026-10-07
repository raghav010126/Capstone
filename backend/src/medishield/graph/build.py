"""The case graph.

    RECEIVED -> [Send per doc] PERCEIVE (quality + OCR + classify + extract)
             -> CLASSIFIED -> [Send per doc, routed by type] SPECIALISTS (KYC | Claims | Claims+Policy)
             -> FRAUD_CHECK (case level) -> DECIDED -> (ESCALATE & HITL on) HUMAN_REVIEW -> END

Routing by document type happens inside the specialist node so each document makes one ``Send`` and the
fan-in is a single super-step. Unknown documents skip the specialists. Agent failures are recorded as
``agent_failed`` facts (-> ESCALATE) instead of crashing the case; a budget overrun stops the run.
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from medishield.agents import claims as claims_agent
from medishield.agents import kyc as kyc_agent
from medishield.agents import policy as policy_agent
from medishield.agents.classifier import classify
from medishield.agents.context import CaseContext, DocView
from medishield.agents.extractor import extract
from medishield.agents.fraud import run_fraud
from medishield.agents.orchestrator import decide_case
from medishield.decision.engine import load_policy
from medishield.fraud.rules import image_hash
from medishield.graph.state import CaseState, DocTask
from medishield.llm import BudgetExceeded, LLMError
from medishield.ocr.engine import run_ocr
from medishield.ocr.quality import assess
from medishield.rag.retrieve import get_store
from medishield.records import get_records
from medishield.schemas import (
    AgentRun,
    ClaimsResult,
    Classification,
    Decision,
    DocType,
    ExtractionResult,
    FraudResult,
    KycResult,
    PolicyResult,
    QualityMetrics,
)


def _cfg(config: RunnableConfig, key: str, default: Any = None) -> Any:
    return (config.get("configurable") or {}).get(key, default)


def _event(node: str, status: str, doc_id: str | None = None, **extra) -> dict:
    return {"ts": time.time(), "node": node, "status": status, "doc_id": doc_id, **extra}


# ── nodes ────────────────────────────────────────────────────────────────────────────────────────────
def received(state: CaseState) -> dict:
    return {"events": [_event("received", "ok", n_docs=len(state["documents"]))]}


def fan_out_perception(state: CaseState) -> list[Send]:
    return [Send("perceive", {"case_id": state["case_id"], "doc": d, "perception": {}, "documents": []})
            for d in state["documents"]]


def perceive(task: DocTask, config: RunnableConfig) -> dict:
    doc = task["doc"]
    doc_id, path = doc["doc_id"], doc["path"]
    records = _cfg(config, "records") or get_records()
    runs: list[dict] = []
    t0 = time.perf_counter()
    lines = run_ocr(path)
    q = assess(path, lines)
    runs.append(AgentRun(agent="preprocess", latency_ms=(time.perf_counter() - t0) * 1000).model_dump())
    out: dict[str, Any] = {"quality": q.model_dump(), "image_hash": image_hash(path), "failed": []}
    try:
        c, run = classify(path, lines, q, tag=doc_id)
        runs.append(run.model_dump())
        out["classification"] = c.model_dump(mode="json")
    except LLMError as e:          # degrade to keyword evidence only; low confidence -> ESCALATE
        from medishield.agents.classifier import keyword_vote

        kw, _ = keyword_vote(lines, q.height)
        out["failed"].append(f"classifier: {e}")
        out["classification"] = Classification(
            doc_type=kw or DocType.UNKNOWN, confidence=0.5, routing_tags=["classifier_failed"],
            llm_doc_type=DocType.UNKNOWN, llm_self_confidence=0.0, keyword_doc_type=kw, keyword_margin=0.0,
            reason=f"LLM unavailable: {e}").model_dump(mode="json")
    forced = (_cfg(config, "forced_types") or {}).get(doc_id)
    if forced:                                           # a human reviewer reclassified this document
        out["classification"].update(doc_type=forced, confidence=1.0, routing_tags=sorted(
            set(out["classification"]["routing_tags"]) | {"reclassified"}),
            reason=f"reclassified by a reviewer (was {out['classification']['doc_type']})")
    dtype = DocType(out["classification"]["doc_type"])
    if dtype != DocType.UNKNOWN and not q.blank:
        try:
            ext, run = extract(path, dtype, lines, q, records, tag=doc_id,
                               language=out["classification"].get("language", "en"))
            runs.append(run.model_dump())
            out["extraction"] = ext.model_dump(mode="json")
        except LLMError as e:
            out["failed"].append(f"extractor: {e}")
    return {"perception": {doc_id: out}, "runs": runs,
            "events": [_event("perceive", "ok" if not out["failed"] else "degraded", doc_id, doc_type=dtype.value)]}


def classified(state: CaseState) -> dict:
    return {"events": [_event("classified", "ok")]}


def fan_out_specialists(state: CaseState) -> list[Send]:
    return [Send("specialists", {"case_id": state["case_id"], "doc": d, "perception": state["perception"],
                                 "documents": state["documents"]}) for d in state["documents"]]


def case_context(case_id: str, documents: list[dict], perception: dict[str, dict]) -> CaseContext:
    ctx = CaseContext(case_id)
    for d in documents:
        p = perception.get(d["doc_id"], {})
        ext = p.get("extraction")
        ctx.docs.append(DocView(d["doc_id"], DocType(p["classification"]["doc_type"]),
                                ext["values"] if ext else {}, ext["confidence"] if ext else 0.0,
                                p.get("image_hash", "")))
    return ctx


def specialists(task: DocTask, config: RunnableConfig) -> dict:
    doc = task["doc"]
    doc_id, path = doc["doc_id"], doc["path"]
    p = task["perception"][doc_id]
    dtype = DocType(p["classification"]["doc_type"])
    out: dict[str, Any] = {"failed": []}
    runs: list[dict] = []
    if dtype == DocType.UNKNOWN or "extraction" not in p:
        return {"specialists": {doc_id: out}, "events": [_event("specialists", "skipped", doc_id)]}
    records = _cfg(config, "records") or get_records()
    ctx = case_context(task["case_id"], task["documents"], task["perception"])
    ext = ExtractionResult.model_validate(p["extraction"])
    tamper_reject = load_policy().get("tamper_action", "REJECT") == "REJECT"
    try:
        if dtype in (DocType.CLAIM_FORM, DocType.ID_DOCUMENT, DocType.POLICY_AMENDMENT):
            quality = QualityMetrics.model_validate(p["quality"]) if p.get("quality") else None
            k, run = kyc_agent.run_kyc(doc_id, path, dtype, ext, ctx, records, tamper_reject, quality)
            out["kyc"] = k.model_dump(mode="json")
            runs.append(run.model_dump())
        if dtype in claims_agent.VALIDATORS:
            out["claims"] = claims_agent.run_claims(dtype, ext).model_dump(mode="json")
            runs.append(AgentRun(agent="claims").model_dump())
        if dtype == DocType.CLAIM_FORM:
            store = _cfg(config, "store") or get_store()
            pol, run = policy_agent.run_policy(ext, ctx, records, store, tag=doc_id)
            out["policy"] = pol.model_dump(mode="json")
            runs.append(run.model_dump())
    except BudgetExceeded:
        raise
    except LLMError as e:
        out["failed"].append(f"specialist: {e}")
    return {"specialists": {doc_id: out}, "runs": runs,
            "events": [_event("specialists", "ok" if not out["failed"] else "degraded", doc_id)]}


def fraud_check(state: CaseState, config: RunnableConfig) -> dict:
    records = _cfg(config, "records") or get_records()
    ctx = case_context(state["case_id"], state["documents"], state["perception"])
    result, new_claims, run = run_fraud(ctx, records, tag=state["case_id"])
    for c in new_claims:                      # later submissions are checked against this case
        records.register(c)
    return {"fraud": result.model_dump(mode="json"), "runs": [run.model_dump()],
            "events": [_event("fraud_check", "ok", risk=result.risk_level.value, score=result.fraud_score)]}


def decided(state: CaseState) -> dict:
    per_doc = []
    for d in state["documents"]:
        p, s = state["perception"][d["doc_id"]], state["specialists"].get(d["doc_id"], {})
        per_doc.append({
            "doc_id": d["doc_id"],
            "classification": Classification.model_validate(p["classification"]),
            "extraction": ExtractionResult.model_validate(p["extraction"]) if "extraction" in p else None,
            "kyc": KycResult.model_validate(s["kyc"]) if "kyc" in s else None,
            "claims": ClaimsResult.model_validate(s["claims"]) if "claims" in s else None,
            "policy": PolicyResult.model_validate(s["policy"]) if "policy" in s else None,
            "failed": p.get("failed", []) + s.get("failed", []),
        })
    fraud = FraudResult.model_validate(state["fraud"]) if state.get("fraud") else None
    decision, run = decide_case(state["case_id"], per_doc, fraud)
    return {"decision": decision.model_dump(mode="json"), "runs": [run.model_dump()],
            "events": [_event("decided", decision.decision.value, confidence=decision.confidence)]}


def needs_review(state: CaseState, config: RunnableConfig) -> str:
    if _cfg(config, "hitl", False) and state["decision"]["decision"] == Decision.ESCALATE.value:
        return "human_review"
    return END


def human_review(state: CaseState) -> dict:
    """Pause for a reviewer. Resume with ``Command(resume={"decision": ..., "reason": ..., "reviewer": ...})``."""
    resolution = interrupt({"case_id": state["case_id"], "decision": state["decision"]})
    return {"review": resolution, "events": [_event("human_review", "resolved", **{
        k: resolution.get(k) for k in ("decision", "reviewer")})]}


def build_graph(checkpointer=None):
    g = StateGraph(CaseState)
    g.add_node("received", received)
    g.add_node("perceive", perceive)
    g.add_node("classified", classified)
    g.add_node("specialists", specialists)
    g.add_node("fraud_check", fraud_check)
    g.add_node("decided", decided)
    g.add_node("human_review", human_review)
    g.add_edge(START, "received")
    g.add_conditional_edges("received", fan_out_perception, ["perceive"])
    g.add_edge("perceive", "classified")
    g.add_conditional_edges("classified", fan_out_specialists, ["specialists"])
    g.add_edge("classified", "fraud_check")                 # fraud reads only the perception, so it runs beside the specialists
    g.add_edge(["specialists", "fraud_check"], "decided")   # the decision waits for both
    g.add_conditional_edges("decided", needs_review, ["human_review", END])
    g.add_edge("human_review", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())
