"""End to end through the real stack: upload -> queue -> LangGraph (OCR, vision agents, RAG, fraud, decision) ->
database -> human-review pause -> four-eyes override -> graph resume -> audit chain -> PDF report.

Model calls are replayed from the on-disk response cache (``MEDISHIELD_LLM_OFFLINE=1``), so this costs nothing and
is deterministic; a cache miss fails the test instead of spending money. Needs ``data/official`` (``make dataset``)
and a warm cache (``make eval``).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from conftest import login
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2] / "data" / "official"
pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not (ROOT / "dataset" / "metadata.json").exists(), reason="dataset not generated")]


def case_files(cluster: str) -> list[tuple[str, bytes]]:
    meta = json.loads((ROOT / "dataset" / "metadata.json").read_text())
    return [(Path(m["file_path"]).name, (ROOT / "dataset" / m["file_path"]).read_bytes())
            for m in meta if m["case_cluster_id"] == cluster]


@pytest.fixture
def real_client(env, monkeypatch):
    """The real app with a real background worker thread (not inline), pointed at the dataset's records."""
    monkeypatch.setenv("MEDISHIELD_QUEUE_IMMEDIATE", "0")
    from conftest import reset_runtime
    reset_runtime()
    from medishield.api import main
    with TestClient(main.create_app()) as c:
        yield c


def wait_for(client, headers, cid, states, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        c = client.get(f"/cases/{cid}", headers=headers).json()
        if c["status"] in states:
            return c
        time.sleep(1)
    raise AssertionError(f"case {cid} stuck in {c['status']}")


def test_cluster_c002_end_to_end(real_client):
    client = real_client
    sub, rev, sen, aud = (login(client, u) for u in ("submitter", "reviewer", "senior", "auditor"))

    # upload the five documents of dataset case C_002 (prescription dated 55 days after the visit)
    r = client.post("/cases", files=[("files", (n, d, "image/png")) for n, d in case_files("C_002")], headers=sub)
    assert r.status_code == 202, r.text
    cid = r.json()["case_id"]

    case = wait_for(client, sub, cid, {"IN_REVIEW", "FAILED", "DECIDED"})
    assert case["status"] == "IN_REVIEW", case.get("error")
    assert case["ai_decision"] == "ESCALATE" and case["display_status"] == "Escalated"
    by_doc = {d["doc_id"]: d for d in case["documents"]}
    rx = by_doc["rx_PT_99733"]
    assert rx["doc_type"] == "PRESCRIPTION" and rx["decision"]["decision"] == "ESCALATE"
    assert any(a["code"] == "rx_date_after_service" for a in case["fraud"]["anomalies"])
    assert by_doc["claim_PT_99733"]["decision"]["decision"] == "APPROVE"
    assert by_doc["claim_PT_99733"]["policy"]["coverage_status"] == "COVERED"
    assert any(f["grounded"] and f["box"] for f in by_doc["claim_PT_99733"]["fields"])      # evidence boxes for the UI
    assert case["total_amount"] == 16825.0

    # live event log covers the whole graph
    nodes = [e["node"] for e in client.get(f"/cases/{cid}/events", headers=sub).json()]
    assert {"queued", "received", "perceive", "classified", "specialists", "fraud_check", "decided", "human_review"} <= set(nodes)

    # it appears in the review queue; $16,825 > $10,000 so the override needs a second approver
    assert cid in [c["id"] for c in client.get("/review/queue", headers=rev).json()]
    ov = client.post(f"/cases/{cid}/override", headers=rev,
                     json={"decision": "APPROVE", "reason_code": "ADDITIONAL_INFORMATION"}).json()
    assert ov["status"] == "PENDING_APPROVAL"
    assert client.get(f"/cases/{cid}", headers=rev).json()["status"] == "IN_REVIEW"
    done = client.post(f"/cases/{cid}/overrides/{ov['id']}/approve", headers=sen).json()
    assert done["status"] == "APPLIED"

    final = client.get(f"/cases/{cid}", headers=rev).json()
    assert final["status"] == "FINALIZED" and final["final_decision"] == "APPROVE" and final["ai_decision"] == "ESCALATE"
    assert "resolved" in [e["status"] for e in client.get(f"/cases/{cid}/events", headers=sub).json() if e["node"] == "human_review"]

    # tamper-evident audit trail and the downloadable report
    assert client.get("/audit/verify", headers=aud).json()["ok"]
    actions = {e["action"] for e in client.get("/audit", params={"case_id": cid, "limit": 200}, headers=aud).json()}
    assert {"case_created", "case_decided", "override_requested", "override_approved", "override_applied"} <= actions
    pdf = client.get(f"/cases/{cid}/report.pdf", headers=rev)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and len(pdf.content) > 20_000     # includes thumbnails
    ops = client.get("/ops/summary", headers=aud).json()
    assert ops["decided"] == 1 and ops["overrides_applied"] == 1


def test_resubmitted_claim_is_flagged_as_duplicate_across_cases(real_client):
    """The processed-claim registry persists across cases: the same claim sent in a second case is a duplicate."""
    client = real_client
    sub = login(client, "submitter")
    files = [f for f in case_files("C_012") if f[0].startswith("claim_")]
    a = client.post("/cases", files=[("files", (files[0][0], files[0][1], "image/png"))], headers=sub).json()["case_id"]
    wait_for(client, sub, a, {"DECIDED", "IN_REVIEW", "FAILED"})
    b = client.post("/cases", files=[("files", ("resubmitted.png", files[0][1], "image/png"))], headers=sub).json()["case_id"]
    second = wait_for(client, sub, b, {"DECIDED", "IN_REVIEW", "FAILED"})
    assert second["status"] != "FAILED", second["error"]
    assert any(a_["code"] == "duplicate_claim" for a_ in second["fraud"]["anomalies"])
