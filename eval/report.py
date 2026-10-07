"""Render an eval result dict as ``docs/EVAL_REPORT.md``."""

from __future__ import annotations

from pathlib import Path


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def write_report(r: dict, path: Path) -> None:
    path.write_text("\n".join(render(r, level=1)) + "\n")


def render(r: dict, level: int = 1) -> list[str]:
    """Markdown for one evaluation run; ``level`` is the heading depth of its title."""
    ex, rt, dc, cs, op = r["extraction"], r["retrieval"], r["decision"], r["cases"], r["ops"]
    L: list[str] = []
    w = L.append
    w(f"{'#' * level} {r['dataset']} / {r['split']} split")
    w("")
    w(f"_Generated {r['timestamp']}. Synthetic benchmark; document and case scores are reported separately._")
    if p := r.get("provenance"):
        w(f"Scoring version {p['scoring_version']}; offline replay: {p['llm_offline']}; "
          f"prefetch: {p['prefetch_enabled']}. Latency scope: {p['latency_scope']}.")
    w("")
    w(f"{'#' * (level + 1)} Rubric metrics")
    w("")
    w("| Rubric criterion (weight) | Metric | Result |")
    w("|---|---|---|")
    w(f"| Classification (20%) | document-type accuracy | **{_pct(r['classification']['accuracy'])}** "
      f"({r['classification']['n']} docs) |")
    w(f"| Extraction (20%) | required claim fields correct (ICD, CPT, line amounts, total, NPI, provider) | "
      f"**{_pct(ex['rubric_claim_completeness'])}** ({ex['rubric_n']} fields) |")
    w(f"| Policy retrieval (15%) | Recall@3 of the governing policy section per billed code / MRR | "
      f"**{_pct(rt['recall@3'])}** / {rt['mrr']} ({rt['queries']} queries) |")
    w(f"| Decision correctness (25%) | per-document decision accuracy, all labels | **{_pct(dc['accuracy_all'])}** "
      f"({dc['n_all']} docs) |")
    w(f"| | ... on labels visible in the pixels | **{_pct(dc['accuracy_visible'])}** ({dc['n_visible']} docs) |")
    w(f"| | case roll-up accuracy | {_pct(cs['accuracy'])} ({cs['n']} cases) |")
    w("")
    w(f"{'#' * (level + 1)} Decisions")
    w("")
    w("Accuracy by true document type: " + ", ".join(f"{k} {_pct(v)}" for k, v in dc["by_type"].items()))
    w("")
    w("Confusion (expected -> predicted): " + ", ".join(f"`{k}` {v}" for k, v in dc["confusion"].items()))
    w("")
    w("**Fraud scenarios detected (per-document score >= 0.3):** "
      + (", ".join(f"{k} {v}" for k, v in r["fraud"]["detected"].items()) or "none in split"))
    w("")
    w(f"False-positive fraud escalations on non-fraud documents: {len(r['fraud']['false_positive_docs'])}"
      + (f" ({', '.join(r['fraud']['false_positive_docs'])})" if r['fraud']['false_positive_docs'] else ""))
    w("")
    w("**Edge cases handled as labelled:** " + ", ".join(f"{k} {v}" for k, v in r["edge_cases"].items()))
    w("")
    if dc["wrong"]:
        w("<details><summary>Decision errors</summary>")
        w("")
        for x in dc["wrong"]:
            w(f"- {x}")
        w("")
        w("</details>")
        w("")
    w(f"{'#' * (level + 1)} Extraction detail")
    w("")
    w(f"All scored fields across document types: **{_pct(ex['all_fields'])}**. By type: "
      + ", ".join(f"{k} {_pct(v)}" for k, v in ex["per_type"].items()))
    w("")
    w("| Field | Accuracy | n |")
    w("|---|---|---|")
    for f, (a, n) in ex["per_field"].items():
        w(f"| {f} | {_pct(a)} | {n} |")
    w("")
    if ex["misses"]:
        w("<details><summary>Field misses</summary>")
        w("")
        for x in ex["misses"][:60]:
            w(f"- {x}")
        w("")
        w("</details>")
        w("")
    w(f"{'#' * (level + 1)} Retrieval detail")
    w("")
    w("Gold sections come from `eval/retrieval_gold.json`, built from the policy text (not retriever output).")
    if rt["misses"]:
        w("")
        w("<details><summary>Queries without a relevant section in the top 3</summary>")
        w("")
        for x in rt["misses"]:
            w(f"- {x}")
        w("")
        w("</details>")
    w("")
    w(f"{'#' * (level + 1)} Operations")
    w("")
    w(f"- Cases: {op['cases']}, documents: {op['docs']}")
    w(f"- Graph latency (cache/prefetch assisted; setup and prefetch excluded): p50 {op['case_latency_s']['p50']}s, "
      f"p95 {op['case_latency_s']['p95']}s")
    w(f"- Cost without cache: ${op['cold_cost_usd']:.2f} total, ${op['cold_cost_per_case_usd']:.3f}/case, "
      f"${op['cold_cost_per_doc_usd']:.3f}/document. Spent this run: ${r['spend_this_run_usd']:.2f}")
    w("- Cost by agent: " + ", ".join(f"{k} ${v:.2f}" for k, v in op["cold_cost_by_agent"].items() if v))
    w(f"- LLM calls: {op['llm_calls']} ({op['cache_hits']} served from cache); retries on Opus: "
      f"{op['retries_by_agent'] or 'none'}")
    w(f"- Mean OCR grounding rate {_pct(op['mean_grounding_rate'])}; mean support rate (grounded or "
      f"corroborated by the member database) {_pct(op['mean_support_rate'])}")
    w("")
    return L
