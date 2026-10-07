import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import metrics as M

GT = {"c": {"policy_number": "MED-GLD-1", "cpt_codes": ["99213", "85025"], "total_charge": 175}}
GOLD = {"plans": {"gold": {c: {"relevant_sections": ["1"]} for c in ("99213", "85025")}}}
ROW = {"doc_id": "c", "true_type": "CLAIM_FORM", "pred_type": "CLAIM_FORM"}


@pytest.mark.parametrize("pred,values", [("CLAIM_FORM", None), ("UNKNOWN", {"total_charge": 175})])
def test_failed_extraction_remains_in_denominator(pred, values):
    score = M.score_extraction([{**ROW, "pred_type": pred, "values": values}], GT)
    assert score["rubric_n"] == 2 and score["rubric_claim_completeness"] == 0
    assert len(score["misses"]) == 3


@pytest.mark.parametrize("plan,ch_plan,chunks", [(None, "gold", 0), ("gold", "gold", 0),
                                                ("silver", "silver", 2), ("gold", "silver", 2), ("gold", "gold", 1)])
def test_missing_queries_and_wrong_plan_count_as_misses(plan, ch_plan, chunks):
    policy = {"plan": plan, "retrieved": [{"query_code": c, "plan": ch_plan, "section": "1 Benefits", "rank": 1}
                                          for c in ["99213", "85025"][:chunks]]} if plan else None
    score = M.score_retrieval([{**ROW, "policy": policy}], GOLD, GT)
    assert score["queries"] == 2
    assert score["recall@3"] == (.5 if plan == ch_plan == "gold" and chunks == 1 else 0)


def test_missing_gold_fails_instead_of_silently_shrinking_denominator():
    with pytest.raises(ValueError, match="Missing retrieval ground truth"):
        M.score_retrieval([ROW], {"plans": {}}, GT)
