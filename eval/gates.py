"""Quality gates over the published evaluation results (no model calls). CI fails if any gate is missed.

Usage: python eval/gates.py      (also: make gates)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RES = Path(__file__).resolve().parents[1] / "docs" / "eval_results"

# (run, metric path, comparison, threshold, label)
GATES = [
    *[(run, ("classification", "accuracy"), ">=", 0.95, "classification accuracy")
      for run in ("official-heldout", "seed7-all", "multilingual-heldout")],
    *[(run, ("extraction", "rubric_claim_completeness"), ">=", 0.95, "claim-field extraction")
      for run in ("official-heldout", "seed7-all")],
    *[(run, ("retrieval", "recall@3"), ">=", 0.90, "policy retrieval recall@3")
      for run in ("official-heldout", "seed7-all")],
    *[(run, ("decision", "accuracy_visible"), ">=", 0.95, "decisions on visible labels")
      for run in ("official-heldout", "seed7-all", "seed7_corrected-all")],
    *[(run, ("decision", "accuracy_all"), ">=", 0.90, "decisions on all labels")
      for run in ("official-heldout", "seed7-all")],
    ("multilingual-heldout", ("decision", "accuracy_all"), ">=", 0.90, "decisions, Spanish + Hindi"),
    ("official-heldout", ("calibration", "all", "calibrated", "ece"), "<=", 0.05, "calibrated ECE (held-out)"),
    ("redteam", ("flips",), "==", 0, "prompt-injection decision flips"),
    ("redteam_policy", ("held",), "==", True, "poisoned policy PDF held"),
    ("chat_redteam", ("failures",), "==", 0, "assistant red-team failures"),
    ("official-heldout", ("ops", "cold_cost_per_case_usd"), "<=", 0.25, "cost per case (USD, uncached)"),
]
OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, "==": lambda a, b: a == b}


def value(run: str, path: tuple):
    p = RES / f"{run}.json"
    if not p.exists():
        return None
    v = json.loads(p.read_text())
    for k in path:
        v = v.get(k) if isinstance(v, dict) else None
    return v


def main() -> int:
    failed = 0
    print(f"{'gate':<40} {'run':<22} {'value':>8}  target")
    for run, path, op, target, label in GATES:
        v = value(run, path)
        ok = v is not None and OPS[op](v, target)
        failed += not ok
        shown = "missing" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))
        print(f"{'PASS' if ok else 'FAIL'}  {label:<34} {run:<22} {shown:>8}  {op} {target}")
    print(f"\n{len(GATES) - failed}/{len(GATES)} gates passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
