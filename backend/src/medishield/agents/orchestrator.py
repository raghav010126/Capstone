"""Orchestrator agent: aggregates agent outputs into facts, applies the decision table, explains the result.

The decision comes from ``decision.engine`` alone. Sonnet then writes the justification for decisions that
are already final; its output is display text and is never read back into any decision.
"""

from __future__ import annotations

import json

from medishield.decision.engine import Facts, decide, decision_confidence, rollup
from medishield.llm import LLMError, structured
from medishield.schemas import (
    AgentRun,
    CaseDecision,
    ClaimsResult,
    Classification,
    CoverageStatus,
    DocType,
    DocumentDecision,
    ExtractionResult,
    FraudResult,
    KycResult,
    PolicyResult,
)
from medishield.schemas.llm_outputs import JustificationRead

SYSTEM = """You write the decision justification for MediShield claims reviewers. The decisions given to you
are FINAL and were made by a deterministic rule engine; explain them, do not change or question them.
For each document write 1-2 sentences citing the specific evidence (agent findings, codes, dates, policy
clause). Then write a 2-3 sentence case justification. Plain, factual language; no speculation.
Use only the facts provided."""


def build_facts(doc_id: str, cls: Classification, ext: ExtractionResult | None, kyc: KycResult | None,
                claims: ClaimsResult | None, policy: PolicyResult | None, fraud: FraudResult | None,
                failed: list[str]) -> Facts:
    f = Facts(doc_unknown=cls.doc_type == DocType.UNKNOWN, classifier_confidence=cls.confidence)
    if f.doc_unknown:
        f.reasons.append(f"classified UNKNOWN ({cls.reason})")
    if cls.confidence < 0.6:
        f.reasons.append(f"classifier confidence {cls.confidence:.2f}")
    if ext is not None:
        f.agent_confidences["extractor"] = ext.confidence
        if ext.confidence < 0.6:
            f.reasons.append(f"extraction confidence {ext.confidence:.2f} (support {ext.support_rate:.0%})")
    if kyc is not None:
        f.agent_confidences["kyc"] = kyc.confidence
        hard = [x for x in kyc.flags if x != "tamper_suspected"]
        if hard:
            f.flags.add("kyc_failed")
            f.reasons.append("KYC failed: " + ", ".join(hard))
        if "tamper_suspected" in kyc.flags:
            f.flags.add("tamper_suspected")
            f.reasons.append("visual tampering suspected (two-model agreement)")
        if kyc.warnings:
            f.reasons.append("KYC warnings: " + ", ".join(kyc.warnings))
    if claims is not None:
        f.agent_confidences["claims"] = claims.confidence
        if not claims.schema_valid:
            f.flags.add("schema_invalid")
            f.reasons.append("claim standard: " + "; ".join(claims.validation_errors[:4]))
    if policy is not None:
        f.agent_confidences["policy"] = policy.confidence
        if policy.coverage_status == CoverageStatus.NOT_COVERED:
            f.flags.add("procedure_not_covered")
            f.reasons.append("not covered: " + "; ".join(policy.exclusions))
        elif policy.coverage_status == CoverageStatus.CONDITIONAL:
            f.flags.add("coverage_conditional")
            f.reasons.append("coverage conditional: " + policy.policy_clause[:160])
    if fraud is not None:
        f.fraud_score = fraud.per_doc_score.get(doc_id, 0.0)
        for a in fraud.anomalies:
            if a.doc_id == doc_id:
                f.reasons.append(f"fraud signal {a.code} (w={a.weight}): {a.detail}")
    if failed:
        f.flags.add("agent_failed")
        f.reasons.append("agent failure: " + ", ".join(failed))
    return f


def decide_case(case_id: str, per_doc: list[dict], fraud: FraudResult | None) -> tuple[CaseDecision, AgentRun]:
    """``per_doc`` items: {doc_id, classification, extraction, kyc, claims, policy, failed} (typed objects)."""
    docs: list[DocumentDecision] = []
    for d in per_doc:
        facts = build_facts(d["doc_id"], d["classification"], d.get("extraction"), d.get("kyc"),
                            d.get("claims"), d.get("policy"), fraud, d.get("failed", []))
        out = decide(facts)
        docs.append(DocumentDecision(doc_id=d["doc_id"], doc_type=d["classification"].doc_type,
                                     decision=out.decision, confidence=decision_confidence(facts, out),
                                     rule_id=out.rule_id, reasons=facts.reasons or ["all checks passed"]))
    case = rollup([x.decision for x in docs])
    conf = min((x.confidence for x in docs if x.decision == case), default=0.0)
    summaries = agent_summaries(per_doc, fraud)
    case_just, run = justify(case_id, case.value, docs, summaries)
    return CaseDecision(case_id=case_id, decision=case, confidence=round(conf, 3), documents=docs,
                        agent_summaries=summaries, justification=case_just), run


def agent_summaries(per_doc: list[dict], fraud: FraudResult | None) -> dict[str, str]:
    s: dict[str, str] = {}
    types = [d["classification"].doc_type.value for d in per_doc]
    s["classifier"] = f"{len(per_doc)} documents: " + ", ".join(sorted(set(types)))
    kyc = [d["kyc"] for d in per_doc if d.get("kyc")]
    if kyc:
        s["kyc"] = f"{sum(k.kyc_passed for k in kyc)}/{len(kyc)} identity checks passed" + (
            "; flags: " + ", ".join(sorted({f for k in kyc for f in k.flags})) if any(k.flags for k in kyc) else "")
    cl = [d["claims"] for d in per_doc if d.get("claims")]
    if cl:
        s["claims"] = f"{sum(c.schema_valid for c in cl)}/{len(cl)} documents meet the submission standard"
    pol = [d["policy"] for d in per_doc if d.get("policy")]
    if pol:
        s["policy"] = "; ".join(f"{p.coverage_status.value} ({p.coverage_percentage}%): {p.policy_clause[:90]}"
                                for p in pol)
    if fraud:
        s["fraud"] = f"risk {fraud.risk_level.value}, score {fraud.fraud_score:.2f}, " \
                     f"{len(fraud.anomalies)} signal(s)"
    return s


def justify(case_id: str, case_decision: str, docs: list[DocumentDecision],
            summaries: dict[str, str]) -> tuple[str, AgentRun]:
    payload = {"case_decision": case_decision, "agent_summaries": summaries,
               "documents": [{"doc_id": d.doc_id, "type": d.doc_type.value, "decision": d.decision.value,
                              "rule": d.rule_id, "evidence": d.reasons} for d in docs]}
    try:
        res = structured("justify", SYSTEM, [json.dumps(payload, indent=1)], JustificationRead, tag=case_id)
    except LLMError as e:
        fallback = f"{case_decision}: " + "; ".join(f"{d.doc_id} {d.decision.value} ({d.rule_id})" for d in docs)
        return f"{fallback}. (Narrative unavailable: {e})", AgentRun(agent="justify")
    by_id = {j.doc_id: j.justification for j in res.parsed.documents}
    for d in docs:
        d.justification = by_id.get(d.doc_id, "; ".join(d.reasons))
    return res.parsed.case_justification, res.run("justify")
