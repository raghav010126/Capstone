import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "datagen"), str(ROOT / "eval")]
from harness import rotation_forward  # noqa: E402
from truth import decide  # noqa: E402

OFFICIAL = ROOT / "data" / "official" / "ground_truth" / "labels.json"


@pytest.mark.parametrize("angle", [-2.0, -0.7, 0.4, 1.9])
def test_rotation_forward_matches_pillow(angle):
    img = Image.new("RGB", (400, 300), "white")
    ImageDraw.Draw(img).rectangle([100, 80, 160, 120], fill="black")
    rot = np.asarray(img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor="white").convert("L"))
    ys, xs = np.where(rot < 128)
    fwd = rotation_forward(400, 300, angle)
    pts = [fwd(x, y) for x, y in ((100, 80), (161, 80), (161, 121), (100, 121))]
    px, py = [p[0] for p in pts], [p[1] for p in pts]
    assert abs(min(px) - xs.min()) <= 2 and abs(max(px) - xs.max()) <= 2
    assert abs(min(py) - ys.min()) <= 2 and abs(max(py) - ys.max()) <= 2


def _meta(**kw):
    base = {"category": "claim_forms", "edge_flags": [], "fraud_label": False, "fraud_reason": None,
            "blur_simulated": False}
    return {**base, **kw}


def test_precedence():
    assert decide(_meta(category="unknown", expected_decision="ESCALATE"))[0] == "ESCALATE"
    # hard failure beats fraud and blur
    assert decide(_meta(edge_flags=["uncovered_procedure"], fraud_label=True))[0] == "REJECT"
    assert decide(_meta(category="prescriptions", edge_flags=["missing_fields"], blur_simulated=True))[0] == "REJECT"
    assert decide(_meta(fraud_label=True, fraud_reason="duplicate_claim"))[0] == "ESCALATE"
    assert decide(_meta(blur_simulated=True))[0] == "ESCALATE"
    assert decide(_meta(category="id_documents", edge_flags=["expiring_soon_id"])) == (
        "APPROVE", ["warning:expiring_soon_id"])
    assert decide(_meta()) == ("APPROVE", [])


@pytest.mark.skipif(not OFFICIAL.exists(), reason="run `make dataset` first")
def test_official_label_counts():
    labels = json.loads(OFFICIAL.read_text())
    docs = labels["documents"]
    counts = {d: sum(v["expected_decision"] == d for v in docs.values()) for d in ("APPROVE", "REJECT", "ESCALATE")}
    assert counts == {"APPROVE": 122, "REJECT": 21, "ESCALATE": 12}
    hidden = sorted(k for k, v in docs.items() if not v["visible"])
    assert hidden == ["claim_PT_69470", "id_PT_39451", "id_PT_57795", "id_PT_62383", "id_PT_74454", "rx_PT_88139"]
    assert len(labels["splits"]["test20"]) == 20
