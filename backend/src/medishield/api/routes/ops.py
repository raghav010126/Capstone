from __future__ import annotations

from fastapi import APIRouter, Depends

from medishield.api.deps import get_db
from medishield.api.security import Principal, require
from medishield.db.repo import Repo
from medishield.llm import ledger

router = APIRouter(tags=["ops"])
# Business context from the assignment brief
BASELINE_DAYS = 4.2
BASELINE_ANNUAL_COST = 18_400_000
MONTHLY_DOCS = 85_000


@router.get("/ops/eval")
def eval_results(_: Principal = Depends(require("ops:read"))):
    """Published evaluation scorecards (written by ``make eval``; committed under docs/eval_results)."""
    import json
    import os
    from pathlib import Path

    from medishield.config import REPO_ROOT

    d = Path(os.environ.get("MEDISHIELD_EVAL_DIR") or REPO_ROOT / "docs" / "eval_results")
    if not d.exists():
        return {}
    runs = {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))}
    # only pipeline evaluation runs (the folder also holds calibrators, red-team and forensics results)
    return {k: v for k, v in runs.items() if isinstance(v, dict) and {"ops", "decision", "classification"} <= v.keys()}


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/ops/summary")
def summary(_: Principal = Depends(require("ops:read")), db: Repo = Depends(get_db)):
    """KPIs for the dashboard: throughput, straight-through-processing, speed, cost and projected savings."""
    cases = db.all_cases()
    done = [c for c in cases if c.status in ("DECIDED", "IN_REVIEW", "FINALIZED")]
    by_final: dict[str, int] = {}
    for c in cases:
        key = c.status if c.status in ("RECEIVED", "PROCESSING", "FAILED") else (c.final_decision or c.ai_decision or "UNKNOWN")
        by_final[key] = by_final.get(key, 0) + 1
    overridden = db.case_ids_with_override_status("APPLIED")
    stp = [c for c in done if c.ai_decision != "ESCALATE" and c.id not in overridden]
    docs = sum(len(c.documents) for c in done)
    avg_cost_case = (sum(c.cold_cost_usd for c in done) / len(done)) if done else 0.0   # uncached unit cost
    avg_docs = (docs / len(done)) if done else 0.0
    cost_per_doc = (avg_cost_case / avg_docs) if avg_docs else 0.0
    review_share = (1 - len(stp) / len(done)) if done else 0.0
    baseline_per_doc = BASELINE_ANNUAL_COST / (MONTHLY_DOCS * 12)
    annual_docs = MONTHLY_DOCS * 12
    # Assumption: a document that needs human review still costs the baseline manual handling.
    projected = annual_docs * (cost_per_doc + review_share * baseline_per_doc)
    return {
        "cases": len(cases), "by_outcome": by_final, "decided": len(done),
        "stp_rate": round(len(stp) / len(done), 4) if done else None,
        "avg_processing_seconds": round(sum(c.wall_ms for c in done) / len(done) / 1000, 1) if done else None,
        "baseline_days_per_claim": BASELINE_DAYS,
        "avg_cost_usd_per_case": round(avg_cost_case, 4), "avg_cost_usd_per_document": round(cost_per_doc, 4),
        "overrides_applied": len(overridden), "open_reviews": sum(c.status == "IN_REVIEW" for c in cases),
        "llm_spend_total_usd": round(ledger().total, 2), "llm_spend_today_usd": round(ledger().spent_today(), 2),
        "business_impact": {
            "baseline_annual_cost_usd": BASELINE_ANNUAL_COST, "baseline_cost_per_document_usd": round(baseline_per_doc, 2),
            "projected_annual_cost_usd": round(projected), "projected_annual_savings_usd": round(BASELINE_ANNUAL_COST - projected),
            "assumptions": "85,000 documents/month; escalated documents still cost baseline manual handling; "
                           "LLM cost from measured per-document spend; excludes infrastructure and staffing changes."},
    }

