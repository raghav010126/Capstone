"""Compare cross-encoder rerankers on the policy-retrieval gold set, offline (no model calls).

The queries are rebuilt exactly as the policy agent builds them, for every (plan, CPT code, description) that appeared on a
claim in the labelled runs; relevance comes from eval/retrieval_gold.json (built from the policy text, never from retriever
output). Usage: python eval/reranker_eval.py [model ...]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval"))

from medishield.agents.policy import TOP_K, service_type
from medishield.rag.ingest import load_or_ingest, policy_pdfs
from medishield.rag.retrieve import PolicyStore
from metrics import _sec

DEFAULT = ["BAAI/bge-reranker-base", "jinaai/jina-reranker-v1-turbo-en", "jinaai/jina-reranker-v1-tiny-en",
           "Xenova/ms-marco-MiniLM-L-12-v2", "Xenova/ms-marco-MiniLM-L-6-v2"]


def queries() -> list[tuple[str, str, str]]:
    """(plan, code, description) seen on claims across the published runs."""
    seen: dict[tuple[str, str], str] = {}
    for run in sorted((REPO / "eval" / "runs").glob("*")):
        rows = run / "rows.json"
        if not rows.exists():
            continue
        for r in json.loads(rows.read_text()):
            pol, vals = r.get("policy") or {}, r.get("values") or {}
            if not pol.get("plan"):
                continue
            for ln in vals.get("service_lines") or []:
                if ln.get("cpt"):
                    seen.setdefault((pol["plan"], ln["cpt"].strip().upper()), ln.get("description") or "")
    return [(p, c, d) for (p, c), d in sorted(seen.items())]


def evaluate(model: str, qs, gold) -> dict:
    t0 = time.perf_counter()
    store = PolicyStore([load_or_ingest(p) for p in policy_pdfs()], rerank_model=model)
    hits = n = 0
    rr = 0.0
    misses = []
    for plan, code, desc in qs:
        g = gold["plans"].get(plan, {}).get(code)
        if not g:
            continue
        kind, hint = service_type(code)
        q = f"CPT {code} {desc}. Service type: {kind}. {hint}"
        secs = [_sec(h.chunk.section) for h in store.search(q, plan, k=TOP_K)]
        rel = set(g["relevant_sections"])
        ranks = [i for i, s in enumerate(secs, 1) if s in rel]
        n += 1
        hits += bool(ranks and ranks[0] <= 3)
        rr += 1 / ranks[0] if ranks else 0.0
        if not ranks or ranks[0] > 3:
            misses.append(f"{plan}:{code} want {sorted(rel)} got {secs}")
    return {"model": model, "queries": n, "recall@3": round(hits / n, 4), "mrr": round(rr / n, 4),
            "seconds": round(time.perf_counter() - t0, 1), "misses": misses}


def main() -> None:
    gold = json.loads((REPO / "eval" / "retrieval_gold.json").read_text())
    qs = queries()
    out = [evaluate(m, qs, gold) for m in (sys.argv[1:] or DEFAULT)]
    for r in out:
        print(f"{r['model']:40s} recall@3 {r['recall@3']:.3f}  MRR {r['mrr']:.3f}  ({r['queries']} queries, {r['seconds']}s)  misses {r['misses'][:3]}")
    (REPO / "docs" / "eval_results" / "reranker.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
