"""Scoring functions for the four rubric metrics plus operational metrics. Pure functions over results."""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict

from medishield.records import iso_dob, name_score

CATEGORY_TO_TYPE = {"claim_forms": "CLAIM_FORM", "id_documents": "ID_DOCUMENT",
                    "discharge_summaries": "DISCHARGE_SUMMARY", "prescriptions": "PRESCRIPTION",
                    "policy_amendments": "POLICY_AMENDMENT", "unknown": "UNKNOWN"}
# Rubric: "% of required fields extracted by the Claims Agent (ICD codes, CPT codes, amounts, provider)"
RUBRIC_CLAIM_FIELDS = ["icd_codes", "cpt_codes", "line_charges", "total_charge", "provider_npi", "billing_provider"]


# ── value comparison ─────────────────────────────────────────────────────────────────────────────────
def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _claim_no(s) -> str:
    m = re.search(r"CLM-?\d{4}-?\d+", str(s or "").upper())
    return re.sub(r"\W", "", m.group(0)) if m else re.sub(r"\W", "", str(s or "").upper())


def same(field: str, gt, got) -> bool:
    if got is None or got == [] or got == "":
        return False
    if field in ("patient_name", "name_on_id", "policyholder", "billing_provider", "attending_physician",
                 "prescriber", "facility"):
        return name_score(str(gt), str(got)) >= 90
    if field in ("patient_dob", "dob"):
        return iso_dob(str(gt)) == iso_dob(str(got))
    if field in ("provider_npi", "prescriber_npi"):
        return _digits(gt) == _digits(got)
    if field == "claim_number":
        return _claim_no(gt) == _claim_no(got)
    if field in ("icd_codes", "cpt_codes", "drugs"):
        return sorted(str(x).upper().strip() for x in gt) == sorted(str(x).upper().strip() for x in got)
    if field == "line_charges":
        return sorted(round(float(x), 2) for x in gt) == sorted(round(float(x), 2) for x in got)
    if field == "total_charge":
        return abs(float(gt) - float(got)) < 0.01
    if field == "amendment_type":
        return str(gt).lower() in str(got).lower() or str(got).lower() in str(gt).lower()
    return str(gt).strip().upper() == str(got).strip().upper()


def extracted_view(doc_type: str, values: dict) -> dict:
    """Map the typed reading onto the ground-truth field names."""
    v = dict(values)
    if doc_type == "CLAIM_FORM":
        lines = v.get("service_lines") or []
        v["cpt_codes"] = [ln["cpt"] for ln in lines if ln.get("cpt")]
        v["line_charges"] = [ln["charge"] for ln in lines if ln.get("charge") is not None]
    if doc_type == "PRESCRIPTION":
        v["drugs"] = [d["name"] for d in v.get("drugs") or [] if d.get("name")]
    return v


SKIP_GT = {"form_type", "id_type", "reference_date", "missing_field", "handwritten"}


def score_extraction(rows: list[dict], fields_gt: dict) -> dict:
    """Field-level accuracy against ground truth. GT None = not visible on the page -> not scored."""
    per_field: dict[str, list[bool]] = defaultdict(list)
    per_type: dict[str, list[bool]] = defaultdict(list)
    rubric: list[bool] = []
    misses: list[str] = []
    for r in rows:
        gt = fields_gt.get(r["doc_id"])
        if gt is None or r.get("values") is None or r["pred_type"] != r["true_type"]:
            continue
        got = extracted_view(r["true_type"], r["values"])
        for f, g in gt.items():
            if f in SKIP_GT or g is None or g == []:
                continue
            ok = same(f, g, got.get(f))
            per_field[f"{r['true_type']}.{f}"].append(ok)
            per_type[r["true_type"]].append(ok)
            if r["true_type"] == "CLAIM_FORM" and f in RUBRIC_CLAIM_FIELDS:
                rubric.append(ok)
            if not ok:
                misses.append(f"{r['doc_id']}.{f}: gt={g!r} got={got.get(f)!r}")
    acc = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    return {"rubric_claim_completeness": acc(rubric), "rubric_n": len(rubric),
            "all_fields": acc([x for v in per_type.values() for x in v]),
            "per_type": {k: acc(v) for k, v in per_type.items()},
            "per_field": {k: (acc(v), len(v)) for k, v in sorted(per_field.items())},
            "misses": misses}


def score_retrieval(rows: list[dict], gold: dict, k: int = 3) -> dict:
    hits, rr, n, misses = 0, 0.0, 0, []
    for r in rows:
        pol = r.get("policy")
        if not pol or not pol.get("plan"):
            continue
        plan_gold = gold["plans"].get(pol["plan"], {})
        by_code: dict[str, list[dict]] = defaultdict(list)
        for ch in pol["retrieved"]:
            by_code[ch["query_code"]].append(ch)
        for code, chunks in by_code.items():
            g = plan_gold.get(code)
            if not g:
                continue
            rel = set(g["relevant_sections"])
            ranks = [c["rank"] for c in sorted(chunks, key=lambda c: c["rank"]) if _sec(c["section"]) in rel]
            n += 1
            if ranks and ranks[0] <= k:
                hits += 1
            rr += 1 / ranks[0] if ranks else 0.0
            if not ranks or ranks[0] > k:
                misses.append(f"{r['doc_id']}:{code} want {sorted(rel)} got "
                              f"{[_sec(c['section']) for c in sorted(chunks, key=lambda c: c['rank'])]}")
    return {f"recall@{k}": round(hits / n, 4) if n else None, "mrr": round(rr / n, 4) if n else None,
            "queries": n, "misses": misses}


def _sec(title: str) -> str:
    m = re.match(r"^(\d+(?:\.\d+)*)", title or "")
    return m.group(1) if m else "0"


def score_decisions(rows: list[dict]) -> dict:
    acc = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    all_ok = [r["pred_decision"] == r["expected_decision"] for r in rows]
    vis_ok = [r["pred_decision"] == r["expected_decision"] for r in rows if r["visible"]]
    by_cat: dict[str, list[bool]] = defaultdict(list)
    conf = Counter()
    for r in rows:
        by_cat[r["true_type"]].append(r["pred_decision"] == r["expected_decision"])
        conf[(r["expected_decision"], r["pred_decision"])] += 1
    wrong = [f"{r['doc_id']}: expected {r['expected_decision']} got {r['pred_decision']} ({r['rule_id']}) "
             f"{'[label not visible] ' if not r['visible'] else ''}- {'; '.join(r['reasons'])[:220]}"
             for r in rows if r["pred_decision"] != r["expected_decision"]]
    return {"accuracy_all": acc(all_ok), "n_all": len(all_ok), "accuracy_visible": acc(vis_ok),
            "n_visible": len(vis_ok), "by_type": {k: acc(v) for k, v in by_cat.items()},
            "confusion": {f"{a}->{b}": c for (a, b), c in sorted(conf.items())}, "wrong": wrong}


def score_cases(case_rows: list[dict]) -> dict:
    ok = [c["pred"] == c["expected"] for c in case_rows]
    return {"accuracy": round(sum(ok) / len(ok), 4) if ok else None, "n": len(ok),
            "wrong": [f"{c['case_id']}: expected {c['expected']} got {c['pred']}" for c in case_rows
                      if c["pred"] != c["expected"]]}


def score_fraud(rows: list[dict]) -> dict:
    scen: dict[str, list[bool]] = defaultdict(list)
    fp = []
    for r in rows:
        reason = next((x.split(":", 1)[1] for x in r["label_reasons"] if x.startswith("fraud:")), None)
        if reason:
            scen[f"{reason}{'' if r['visible'] else ' (not visible)'}"].append(r["fraud_score"] >= 0.3)
        elif r["fraud_score"] >= 0.3:
            fp.append(f"{r['doc_id']} score={r['fraud_score']}")
    return {"detected": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(scen.items())},
            "false_positive_docs": fp}


def score_edges(rows: list[dict]) -> dict:
    want = {"expired_id": "REJECT", "missing_fields": "REJECT", "uncovered_procedure": "REJECT",
            "tampered_id": "REJECT", "blurred_scan": "ESCALATE", "unknown_document": "ESCALATE",
            "expiring_soon_id": "APPROVE"}
    out: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        for reason in r["label_reasons"]:
            key = reason.split(":")[-1]
            if key in want:
                tag = key + ("" if r["visible"] else " (not visible)")
                out[tag].append(r["pred_decision"] == want[key])
    return {k: f"{sum(v)}/{len(v)}" for k, v in sorted(out.items())}


def ops(rows: list[dict], cases: list[dict], runs: list[dict]) -> dict:
    walls = sorted(c["wall_ms"] / 1000 for c in cases)
    q = lambda xs, p: round(xs[min(len(xs) - 1, int(p * len(xs)))], 1) if xs else None
    cost = sum(r.get("cost_usd", 0) for r in runs)
    cold = sum(r.get("cold_cost_usd", 0) for r in runs)
    calls = sum(r.get("llm_calls", 0) for r in runs)
    retries = Counter(r["agent"] for r in runs if r.get("retried_with"))
    by_agent: dict[str, float] = defaultdict(float)
    for r in runs:
        by_agent[r["agent"]] += r.get("cold_cost_usd", 0)
    grounding = [r["grounding_rate"] for r in rows if r.get("grounding_rate") is not None]
    support = [r["support_rate"] for r in rows if r.get("support_rate") is not None]
    return {"cases": len(cases), "docs": len(rows),
            "case_latency_s": {"p50": q(walls, 0.5), "p95": q(walls, 0.95), "max": walls[-1] if walls else None},
            "cost_usd_new_calls": round(cost, 4), "cold_cost_usd": round(cold, 4),
            "cold_cost_per_case_usd": round(cold / len(cases), 4) if cases else None,
            "cold_cost_per_doc_usd": round(cold / len(rows), 4) if rows else None,
            "llm_calls": calls, "cache_hits": sum(r.get("cache_hits", 0) for r in runs),
            "retries_by_agent": dict(retries), "cold_cost_by_agent": {k: round(v, 4) for k, v in by_agent.items()},
            "mean_grounding_rate": round(statistics.mean(grounding), 4) if grounding else None,
            "mean_support_rate": round(statistics.mean(support), 4) if support else None}


def by_language(rows: list[dict], fields_gt: dict) -> dict:
    """Per-language results for a multilingual dataset (documents are named ``..._es`` / ``..._hi``); {} otherwise."""
    import re

    lang_of = lambda r: (m.group(1) if (m := re.search(r"_(es|hi)(?:_|$)", r["doc_id"])) else None)
    langs = sorted({lang_of(r) for r in rows} - {None})
    out = {}
    for lang in langs:
        sub = [r for r in rows if lang_of(r) == lang]
        ext = score_extraction(sub, fields_gt)
        out[lang] = {"documents": len(sub),
                     "classification": round(sum(r["pred_type"] == r["true_type"] for r in sub) / len(sub), 4),
                     "extraction_all_fields": ext["all_fields"], "extraction_misses": ext["misses"][:12],
                     "decision": round(sum(r["pred_decision"] == r["expected_decision"] for r in sub) / len(sub), 4),
                     "mean_classifier_confidence": round(sum(r["cls_confidence"] for r in sub) / len(sub), 3)}
    return out
