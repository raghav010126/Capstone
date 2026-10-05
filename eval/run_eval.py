"""Evaluate the pipeline on a split of a generated dataset and write ``docs/EVAL_REPORT.md``.

* Whole cases run through the real LangGraph case graph, **sequentially and in submission order** (so an
  original claim is processed before its ``_dup`` re-submission, and the processed-claim registry carries
  across cases exactly as in production).
* A parallel *prefetch* first warms the response cache for the per-document perception calls (identical
  prompts, so the graph then replays them); it only changes wall-clock time, not results.
* Prompt iteration happens on ``dev`` only; ``heldout``/``seed7`` numbers are reported, never tuned on.

Usage: python eval/run_eval.py --split dev [--dataset data/official] [--workers 6] [--cases C_001,C_002]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval"))

import metrics as M
from medishield.graph.build import perceive
from medishield.llm import ledger
from medishield.pipeline import run_case
from medishield.rag.retrieve import get_store
from medishield.records import load_records


def load(root: Path):
    meta = json.loads((root / "dataset" / "metadata.json").read_text())
    labels = json.loads((root / "ground_truth" / "labels.json").read_text())
    fields = json.loads((root / "ground_truth" / "fields.json").read_text())
    return meta, labels, fields


def select(meta: list[dict], labels: dict, split: str, only: set[str] | None) -> dict[str, list[dict]]:
    """case_id -> documents in submission (metadata) order."""
    if split == "all":
        keep = {lab["case_id"] for lab in labels["documents"].values()}
    elif split == "test20":
        ids = set(labels["splits"]["test20"])
        keep = {labels["documents"][d]["case_id"] for d in ids}
    else:
        keep = set(labels["splits"][f"{split}_clusters"]) | set(labels["splits"][f"{split}_unknown"])
    cases: dict[str, list[dict]] = {}
    for m in meta:
        cid = labels["documents"][m["doc_id"]]["case_id"]
        if cid in keep and (not only or cid in only):
            if split == "test20" and m["doc_id"] not in labels["splits"]["test20"]:
                continue
            cases.setdefault(cid, []).append(m)
    return dict(sorted(cases.items()))


def prefetch(root: Path, cases: dict[str, list[dict]], records, workers: int) -> None:
    docs = [m for ms in cases.values() for m in ms]
    cfg = {"configurable": {"records": records}}

    def one(m):
        perceive({"case_id": "", "doc": {"doc_id": m["doc_id"], "path": str(root / "dataset" / m["file_path"])},
                  "perception": {}, "documents": []}, cfg)

    t0 = time.time()
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, docs))
    print(f"[prefetch] {len(docs)} documents in {time.time() - t0:.0f}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "heldout", "all", "test20"])
    ap.add_argument("--dataset", default=str(REPO / "data" / "official"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--cases", default="")
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()

    root = Path(args.dataset)
    meta, labels, fields_gt = load(root)
    cases = select(meta, labels, args.split, set(filter(None, args.cases.split(","))) or None)
    records = load_records(root)
    store = get_store()
    spend0 = ledger().total
    prefetch(root, cases, records, args.workers)

    rows, case_rows, runs = [], [], []
    t0 = time.time()
    for cid, ms in cases.items():
        st = run_case(cid, [(m["doc_id"], root / "dataset" / m["file_path"]) for m in ms], records, store)
        dec = st["decision"]
        runs.extend(st.get("runs", []))
        case_rows.append({"case_id": cid, "pred": dec["decision"], "expected": labels["cases"][cid],
                          "wall_ms": st["wall_ms"], "confidence": dec["confidence"]})
        for d in dec["documents"]:
            lab = labels["documents"][d["doc_id"]]
            p, s = st["perception"][d["doc_id"]], st["specialists"].get(d["doc_id"], {})
            ext = p.get("extraction")
            rows.append({
                "doc_id": d["doc_id"], "case_id": cid, "true_type": M.CATEGORY_TO_TYPE[lab["category"]],
                "pred_type": p["classification"]["doc_type"], "cls_confidence": p["classification"]["confidence"],
                "expected_decision": lab["expected_decision"], "pred_decision": d["decision"],
                "confidence": d["confidence"], "rule_id": d["rule_id"], "reasons": d["reasons"],
                "visible": lab["visible"], "label_reasons": lab["reasons"],
                "values": ext["values"] if ext else None,
                "grounding_rate": ext["grounding_rate"] if ext else None,
                "support_rate": ext["support_rate"] if ext else None,
                "policy": s.get("policy"), "kyc": s.get("kyc"), "claims": s.get("claims"),
                "fraud_score": st["fraud"]["per_doc_score"].get(d["doc_id"], 0.0),
                "justification": d.get("justification", ""),
            })
        print(f"[case] {cid}: {dec['decision']:8s} (expected {labels['cases'][cid]:8s}) "
              f"{st['wall_ms'] / 1000:5.1f}s  spend so far ${ledger().total - spend0:.2f}")
    elapsed = time.time() - t0

    gold = json.loads((REPO / "eval" / "retrieval_gold.json").read_text())
    cls_ok = [r["pred_type"] == r["true_type"] for r in rows]
    result = {
        "split": args.split, "dataset": root.name, "timestamp": datetime.now().isoformat(timespec="seconds"),
        "classification": {"accuracy": round(sum(cls_ok) / len(cls_ok), 4), "n": len(cls_ok),
                           "wrong": [f"{r['doc_id']}: {r['true_type']} -> {r['pred_type']}" for r in rows
                                     if r["pred_type"] != r["true_type"]]},
        "extraction": M.score_extraction(rows, fields_gt),
        "retrieval": M.score_retrieval(rows, gold),
        "decision": M.score_decisions(rows),
        "cases": M.score_cases(case_rows),
        "fraud": M.score_fraud(rows),
        "edge_cases": M.score_edges(rows),
        "ops": M.ops(rows, case_rows, runs),
        "spend_this_run_usd": round(ledger().total - spend0, 4),
        "graph_seconds": round(elapsed, 1),
    }
    out_dir = REPO / "eval" / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}-{root.name}-{args.split}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(result, indent=1, default=str))
    (out_dir / "rows.json").write_text(json.dumps(rows, indent=1, default=str))
    if not args.cases:                         # full-split runs are published for the Insights page
        pub = REPO / "docs" / "eval_results"
        pub.mkdir(exist_ok=True)
        (pub / f"{root.name}-{args.split}.json").write_text(json.dumps(result, indent=1, default=str))
    if not args.no_report:
        from report import write_report

        write_report(result, REPO / "docs" / "EVAL_REPORT.md")
    print(json.dumps({k: result[k] for k in ("classification", "decision", "cases")}, default=str)[:1500])
    print(f"-> {out_dir}")


if __name__ == "__main__":
    main()
