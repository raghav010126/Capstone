"""Verdict for the prompt-injection red team: did any attacked document get a decision different from its label?

Reads the rows of the latest ``eval/run_eval.py --dataset data/redteam --split all`` run and the attack manifest.
Usage: python eval/redteam_report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    manifest = json.loads((REPO / "data" / "redteam" / "redteam_manifest.json").read_text())
    run = max((REPO / "eval" / "runs").glob("*redteam-all"))
    rows = {r["doc_id"]: r for r in json.loads((run / "rows.json").read_text())}
    records, flips = [], 0
    for m in manifest:
        r = rows[m["target"]]
        flipped = r["pred_decision"] != m["expected"]
        flips += flipped
        v = r.get("values") or {}
        records.append({"attack": m["attack"], "expected": m["expected"], "decision": r["pred_decision"], "rule": r["rule_id"], "flipped": flipped,
                        "classified_as": r["pred_type"], "reasons": r["reasons"][:3],
                        "cpt_extracted": [ln.get("cpt") for ln in (v.get("service_lines") or [])]})
    out = {"attacks": len(manifest), "flips": flips, "results": records, "source_run": run.name}
    (REPO / "docs" / "eval_results" / "redteam.json").write_text(json.dumps(out, indent=1))
    for r in records:
        print(f"{'FLIP ' if r['flipped'] else 'ok   '} {r['attack']:24s} expected {r['expected']:9s} got {r['decision']:9s} via {r['rule']}")
    print(f"\n{flips} decision flips in {len(manifest)} attacks")
    return 1 if flips else 0


if __name__ == "__main__":
    sys.exit(main())
