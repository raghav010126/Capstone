from __future__ import annotations

import io

import pytest
from conftest import PASSWORDS, png_bytes, upload
from PIL import Image

ROLES = list(PASSWORDS)


# ── authentication ───────────────────────────────────────────────────────────────────────────────────
def test_login_and_me(client):
    r = client.post("/auth/login", json={"username": "reviewer", "password": PASSWORDS["reviewer"]})
    assert r.status_code == 200 and r.json()["role"] == "reviewer"
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert "review:override" in me["permissions"] and "policy:upload" not in me["permissions"]


def test_bad_credentials_and_unknown_user_look_identical(client):
    a = client.post("/auth/login", json={"username": "reviewer", "password": "wrong"})
    b = client.post("/auth/login", json={"username": "nobody", "password": "wrong"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_token_required_and_tampered_token_rejected(client, auth):
    assert client.get("/cases").status_code == 401
    bad = auth("admin")["Authorization"][:-3] + "abc"
    assert client.get("/cases", headers={"Authorization": bad}).status_code == 401


def test_login_rate_limit(client, monkeypatch):
    monkeypatch.setenv("LOGIN_RATE_PER_MIN", "3")
    from conftest import reset_runtime
    reset_runtime()
    codes = [client.post("/auth/login", json={"username": "reviewer", "password": "x"}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3] == 429


# ── RBAC matrix ──────────────────────────────────────────────────────────────────────────────────────
# (method, path template, permission-granting roles). Every route and every role is exercised.
MATRIX = [
    ("GET", "/cases", set(ROLES)),
    ("GET", "/cases/{c}", set(ROLES)),
    ("GET", "/cases/{c}/events", set(ROLES)),
    ("GET", "/cases/{c}/documents/doc0/image", set(ROLES)),
    ("GET", "/review/queue", {"reviewer", "senior", "auditor", "admin"}),
    ("GET", "/review/reason-codes", {"reviewer", "senior", "auditor", "admin"}),
    ("GET", "/cases/{c}/overrides", {"reviewer", "senior", "auditor", "admin"}),
    ("GET", "/audit", {"auditor", "senior", "admin"}),
    ("GET", "/audit/verify", {"auditor", "senior", "admin"}),
    ("GET", "/cases/{c}/report.pdf", {"reviewer", "senior", "auditor", "admin"}),
    ("GET", "/policies", {"reviewer", "senior", "auditor", "admin"}),
    ("GET", "/ops/summary", {"reviewer", "senior", "auditor", "admin"}),
    ("GET", "/users", {"admin"}),
]


@pytest.mark.parametrize("method,path,allowed", MATRIX)
def test_rbac_matrix_reads(client, auth, fake_pipeline, method, path, allowed):
    cid = upload(client, auth("submitter")).json()["case_id"]
    for role in ROLES:
        r = client.request(method, path.format(c=cid), headers=auth(role))
        if role in allowed:
            assert r.status_code != 403, f"{role} should be allowed on {method} {path}: {r.text[:200]}"
            assert r.status_code < 500
        else:
            assert r.status_code == 403, f"{role} must be denied on {method} {path}"


def test_rbac_matrix_writes(client, auth, fake_pipeline):
    fake_pipeline.amount = 100.0
    cid = upload(client, auth("submitter")).json()["case_id"]
    body = {"decision": "APPROVE", "reason_code": "CONFIRMED_AI_DECISION", "note": ""}
    for role in ("submitter", "auditor"):                                   # may not override
        assert client.post(f"/cases/{cid}/override", json=body, headers=auth(role)).status_code == 403
    assert client.post(f"/cases/{cid}/documents/doc0/reclassify", headers=auth("auditor"),
                       json={"doc_type": "UNKNOWN", "reason_code": "CLASSIFICATION_ERROR"}).status_code == 403
    pdf = io.BytesIO(b"%PDF-1.4 x")
    for role in ("submitter", "reviewer", "senior", "auditor"):             # only admin uploads policies
        r = client.post("/policies", data={"plan": "gold"}, files={"file": ("p.pdf", pdf, "application/pdf")}, headers=auth(role))
        assert r.status_code == 403
    for role in ("auditor",):                                               # auditors are read-only
        assert upload(client, auth(role)).status_code == 403
    assert client.post("/cases/x/overrides/1/approve", headers=auth("reviewer")).status_code == 403


def test_submitters_only_see_their_own_cases(client, auth, fake_pipeline):
    from conftest import add_user
    from medishield.api.security import Role

    add_user("submitter2", Role.SUBMITTER.value, "pw-two", "S2")
    other = client.post("/auth/login", json={"username": "submitter2", "password": "pw-two"}).json()["access_token"]
    other = {"Authorization": f"Bearer {other}"}
    mine = upload(client, auth("submitter")).json()["case_id"]
    assert client.get(f"/cases/{mine}", headers=other).status_code == 404       # 404, not 403: ids can't be probed
    assert client.get("/cases", headers=other).json() == []
    assert [c["id"] for c in client.get("/cases", headers=auth("submitter")).json()] == [mine]
    assert [c["id"] for c in client.get("/cases", headers=auth("reviewer")).json()] == [mine]


# ── upload hardening ─────────────────────────────────────────────────────────────────────────────────
def test_upload_rejects_wrong_magic_bytes(client, auth, fake_pipeline):
    r = client.post("/cases", files=[("files", ("claim.png", b"<html>not an image</html>", "image/png"))], headers=auth("submitter"))
    assert r.status_code == 415


def test_upload_rejects_executable_disguised_as_pdf(client, auth, fake_pipeline):
    r = client.post("/cases", files=[("files", ("x.pdf", b"MZ\x90\x00" + b"\x00" * 100, "application/pdf"))], headers=auth("submitter"))
    assert r.status_code == 415


def test_upload_rejects_oversize(client, auth, fake_pipeline, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "200")
    from conftest import reset_runtime
    reset_runtime()
    assert upload(client, auth("submitter")).status_code == 413


def test_upload_rejects_corrupt_png(client, auth, fake_pipeline):
    data = b"\x89PNG\r\n\x1a\n" + b"garbage" * 20
    assert client.post("/cases", files=[("files", ("a.png", data, "image/png"))], headers=auth("submitter")).status_code == 422


def test_upload_rejects_decompression_bomb(client, auth, fake_pipeline):
    """A tiny file declaring a huge canvas is rejected on its header, before pixels are decoded."""
    from medishield.config import get_settings
    pixels = get_settings().max_image_pixels
    side = int(pixels ** 0.5) + 200
    im = Image.new("1", (side, side), 1)                        # 1-bit: a few KB compressed, tens of millions of pixels
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    assert buf.tell() < get_settings().max_upload_bytes
    r = client.post("/cases", files=[("files", ("bomb.png", buf.getvalue(), "image/png"))], headers=auth("submitter"))
    assert r.status_code == 422 and ("large" in r.text or "bomb" in r.text)


def test_upload_rejects_pdf_with_too_many_pages(client, auth, fake_pipeline):
    from fpdf import FPDF
    pdf = FPDF()
    for _ in range(11):
        pdf.add_page()
    r = client.post("/cases", files=[("files", ("big.pdf", bytes(pdf.output()), "application/pdf"))], headers=auth("submitter"))
    assert r.status_code == 422 and "pages" in r.text


def test_pdf_is_split_into_one_document_per_page(client, auth, fake_pipeline):
    from fpdf import FPDF
    pdf = FPDF()
    for i in range(2):
        pdf.add_page()
        pdf.set_font("Helvetica", size=24)
        pdf.cell(text=f"Page {i}")
    r = client.post("/cases", files=[("files", ("scan.pdf", bytes(pdf.output()), "application/pdf"))], headers=auth("submitter"))
    assert r.status_code == 202 and r.json()["documents"] == ["scan_p1", "scan_p2"]


def test_multiframe_tiff_is_accepted(client, auth, fake_pipeline):
    frames = [Image.new("RGB", (200, 200), c) for c in ("white", "gray", "black")]
    buf = io.BytesIO()
    frames[0].save(buf, format="TIFF", save_all=True, append_images=frames[1:])
    r = client.post("/cases", files=[("files", ("fax.tiff", buf.getvalue(), "image/tiff"))], headers=auth("submitter"))
    assert r.status_code == 202 and len(r.json()["documents"]) == 3


def test_filename_cannot_escape_storage(client, auth, fake_pipeline):
    r = client.post("/cases", files=[("files", ("../../etc/passwd.png", png_bytes(), "image/png"))], headers=auth("submitter"))
    assert r.status_code == 202 and r.json()["documents"] == ["passwd"]


def test_too_many_files(client, auth, fake_pipeline):
    assert upload(client, auth("submitter"), n=11).status_code == 413


def test_upload_rate_limit(client, auth, fake_pipeline, monkeypatch):
    monkeypatch.setenv("UPLOAD_RATE_PER_MIN", "2")
    from conftest import reset_runtime
    reset_runtime()
    h = auth("submitter")
    assert [upload(client, h, n=1).status_code for _ in range(3)] == [202, 202, 429]


def test_idempotent_upload_returns_the_same_case(client, auth, fake_pipeline):
    h = {**auth("submitter"), "Idempotency-Key": "retry-123"}
    first, second = upload(client, h), upload(client, h)
    assert first.status_code == 202 and second.status_code == 200
    assert first.json()["case_id"] == second.json()["case_id"] and second.json()["idempotent_replay"]
    assert len(client.get("/cases", headers=auth("reviewer")).json()) == 1


def test_identical_files_in_one_upload_are_deduplicated(client, auth, fake_pipeline):
    same = png_bytes()
    r = client.post("/cases", files=[("files", ("a.png", same, "image/png")), ("files", ("b.png", same, "image/png"))],
                    headers=auth("submitter"))
    assert r.json()["documents"] == ["a"] and r.json()["warnings"]


def test_daily_budget_pauses_uploads(client, auth, fake_pipeline, monkeypatch):
    monkeypatch.setenv("MEDISHIELD_DAILY_BUDGET_USD", "0.01")
    from conftest import reset_runtime
    from medishield.llm import ledger
    reset_runtime()
    ledger().record("t", "claude-sonnet-5-5", __import__("medishield.llm.cost", fromlist=["Usage"]).Usage(), 0.5)
    r = upload(client, auth("submitter"))
    assert r.status_code == 503 and "budget" in r.text


# ── processing & case views ──────────────────────────────────────────────────────────────────────────
def test_case_is_processed_and_visible(client, auth, fake_pipeline):
    fake_pipeline.decision = "APPROVE"
    cid = upload(client, auth("submitter")).json()["case_id"]
    c = client.get(f"/cases/{cid}", headers=auth("submitter")).json()
    assert c["status"] == "DECIDED" and c["display_status"] == "Approved" and c["final_decision"] == "APPROVE"
    assert c["decision"]["justification"] == "test justification" and len(c["documents"]) == 2
    assert c["agent_runs"][0]["agent"] == "classifier" and c["documents"][0]["image_url"].endswith("/image")
    img = client.get(c["documents"][0]["image_url"], headers=auth("submitter"))
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"


def test_pipeline_failure_marks_case_failed_not_500(client, auth, fake_pipeline):
    fake_pipeline.fail = RuntimeError("boom with SSN 123-45-6789")
    cid = upload(client, auth("submitter")).json()["case_id"]
    c = client.get(f"/cases/{cid}", headers=auth("submitter")).json()
    assert c["status"] == "FAILED" and "123-45-6789" not in (c["error"] or "")


def test_events_are_recorded_in_order(client, auth, fake_pipeline):
    cid = upload(client, auth("submitter")).json()["case_id"]
    nodes = [e["node"] for e in client.get(f"/cases/{cid}/events", headers=auth("submitter")).json()]
    assert nodes[0] == "queued" and "perceive" in nodes and nodes[-1] == "decided"


def test_websocket_streams_events_then_done(client, auth, fake_pipeline):
    cid = upload(client, auth("submitter")).json()["case_id"]
    token = auth("submitter")["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/cases/{cid}?token={token}") as ws:
        msgs = []
        while True:
            m = ws.receive_json()
            msgs.append(m)
            if m["type"] != "event":
                break
    assert [m["type"] for m in msgs][-1] == "done" and any(m.get("node") == "perceive" for m in msgs)


def test_websocket_rejects_bad_token_and_other_users_case(client, auth, fake_pipeline):
    cid = upload(client, auth("submitter")).json()["case_id"]
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(f"/ws/cases/{cid}?token=nope") as ws:
        ws.receive_json()


def test_sse_fallback_streams(client, auth, fake_pipeline):
    cid = upload(client, auth("submitter")).json()["case_id"]
    r = client.get(f"/cases/{cid}/stream", headers=auth("submitter"))
    assert r.status_code == 200 and "data: " in r.text and '"type": "done"' in r.text


# ── review: overrides, reason codes, four-eyes ───────────────────────────────────────────────────────
def override(client, headers, cid, decision="APPROVE", reason="DOCUMENT_VERIFIED_MANUALLY", note=""):
    return client.post(f"/cases/{cid}/override", json={"decision": decision, "reason_code": reason, "note": note}, headers=headers)


def test_low_value_override_applies_immediately_and_resumes_graph(client, auth, fake_pipeline):
    fake_pipeline.amount = 4000
    cid = upload(client, auth("submitter")).json()["case_id"]
    assert client.get(f"/cases/{cid}", headers=auth("reviewer")).json()["status"] == "IN_REVIEW"
    r = override(client, auth("reviewer"), cid)
    assert r.status_code == 201 and r.json()["status"] == "APPLIED" and not r.json()["requires_four_eyes"]
    c = client.get(f"/cases/{cid}", headers=auth("reviewer")).json()
    assert c["status"] == "FINALIZED" and c["final_decision"] == "APPROVE" and c["ai_decision"] == "ESCALATE"
    assert fake_pipeline.resumed and fake_pipeline.resumed[0][1]["decision"] == "APPROVE"


def test_reason_code_is_mandatory_and_validated(client, auth, fake_pipeline):
    cid = upload(client, auth("submitter")).json()["case_id"]
    assert override(client, auth("reviewer"), cid, reason="BECAUSE").status_code == 422
    assert override(client, auth("reviewer"), cid, reason="OTHER", note="short").status_code == 422
    assert override(client, auth("reviewer"), cid, decision="MAYBE").status_code == 422
    assert override(client, auth("reviewer"), cid, reason="OTHER", note="verified by phone with the provider").status_code == 201


def test_high_value_override_requires_a_second_senior_approver(client, auth, fake_pipeline):
    fake_pipeline.amount = 25000
    cid = upload(client, auth("submitter")).json()["case_id"]
    ov = override(client, auth("reviewer"), cid).json()
    assert ov["status"] == "PENDING_APPROVAL" and ov["requires_four_eyes"]
    assert client.get(f"/cases/{cid}", headers=auth("reviewer")).json()["status"] == "IN_REVIEW"     # nothing applied yet
    assert override(client, auth("senior"), cid).status_code == 409                                  # one pending at a time
    base = f"/cases/{cid}/overrides/{ov['id']}"
    assert client.post(f"{base}/approve", headers=auth("reviewer")).status_code == 403               # role too low
    assert client.post(f"{base}/approve", headers=auth("senior")).json()["status"] == "APPLIED"
    c = client.get(f"/cases/{cid}", headers=auth("reviewer")).json()
    assert c["status"] == "FINALIZED" and c["final_decision"] == "APPROVE" and fake_pipeline.resumed
    assert client.post(f"{base}/approve", headers=auth("admin")).status_code == 409                  # already resolved


def test_nobody_can_approve_their_own_override(client, auth, fake_pipeline):
    fake_pipeline.amount = 25000
    cid = upload(client, auth("submitter")).json()["case_id"]
    ov = override(client, auth("senior"), cid).json()
    assert ov["status"] == "PENDING_APPROVAL"                                    # seniors need a second person too
    base = f"/cases/{cid}/overrides/{ov['id']}"
    assert client.post(f"{base}/approve", headers=auth("senior")).status_code == 403
    assert client.post(f"{base}/reject", json={}, headers=auth("senior")).status_code == 403
    assert client.post(f"{base}/approve", headers=auth("admin")).status_code == 200


def test_rejected_override_leaves_case_in_review(client, auth, fake_pipeline):
    fake_pipeline.amount = 25000
    cid = upload(client, auth("submitter")).json()["case_id"]
    ov = override(client, auth("reviewer"), cid).json()
    r = client.post(f"/cases/{cid}/overrides/{ov['id']}/reject", json={"note": "evidence insufficient"}, headers=auth("senior"))
    assert r.json()["status"] == "REJECTED"
    assert client.get(f"/cases/{cid}", headers=auth("reviewer")).json()["status"] == "IN_REVIEW"
    assert override(client, auth("reviewer"), cid).status_code == 201            # may try again


def test_automated_decisions_can_be_overridden_without_a_graph_resume(client, auth, fake_pipeline):
    fake_pipeline.decision, fake_pipeline.amount = "APPROVE", 100
    cid = upload(client, auth("submitter")).json()["case_id"]
    assert override(client, auth("reviewer"), cid, decision="REJECT", reason="CONFIRMED_FRAUD").status_code == 201
    assert client.get(f"/cases/{cid}", headers=auth("reviewer")).json()["final_decision"] == "REJECT"
    assert not fake_pipeline.resumed


def test_review_queue_orders_by_sla_then_risk(client, auth, fake_pipeline):
    fake_pipeline.risk = 0.4
    low = upload(client, auth("submitter"), n=1).json()["case_id"]
    fake_pipeline.risk = 0.9
    high = upload(client, auth("submitter"), n=1).json()["case_id"]
    q = [c["id"] for c in client.get("/review/queue", headers=auth("reviewer")).json()]
    assert q == [high, low]


def test_reclassify_requeues_the_case(client, auth, fake_pipeline):
    cid = upload(client, auth("submitter")).json()["case_id"]
    r = client.post(f"/cases/{cid}/documents/doc0/reclassify", headers=auth("reviewer"),
                    json={"doc_type": "PRESCRIPTION", "reason_code": "CLASSIFICATION_ERROR"})
    assert r.status_code == 202
    c = client.get(f"/cases/{cid}", headers=auth("reviewer")).json()
    assert next(d for d in c["documents"] if d["doc_id"] == "doc0")["forced_type"] == "PRESCRIPTION"
    bad = client.post(f"/cases/{cid}/documents/doc0/reclassify", headers=auth("reviewer"),
                      json={"doc_type": "SPAM", "reason_code": "CLASSIFICATION_ERROR"})
    assert bad.status_code == 422


# ── audit chain ──────────────────────────────────────────────────────────────────────────────────────
def test_audit_chain_verifies_and_covers_the_workflow(client, auth, fake_pipeline):
    fake_pipeline.amount = 25000
    cid = upload(client, auth("submitter")).json()["case_id"]
    ov = override(client, auth("reviewer"), cid).json()
    client.post(f"/cases/{cid}/overrides/{ov['id']}/approve", headers=auth("senior"))
    v = client.get("/audit/verify", headers=auth("auditor")).json()
    assert v["ok"] and v["length"] >= 6
    actions = [e["action"] for e in client.get("/audit", params={"case_id": cid, "limit": 100}, headers=auth("auditor")).json()]
    assert {"case_created", "case_decided", "override_requested", "override_approved", "override_applied"} <= set(actions)


def test_audit_detects_edited_event(client, auth, fake_pipeline):
    from conftest import tamper_audit
    upload(client, auth("submitter"))
    tamper_audit(2, actor="mallory")
    v = client.get("/audit/verify", headers=auth("auditor")).json()
    assert not v["ok"] and v["broken_at"] == 2 and "content" in v["reason"]


def test_audit_detects_deleted_event(client, auth, fake_pipeline):
    from conftest import tamper_audit
    upload(client, auth("submitter"))
    tamper_audit(2, delete=True)
    v = client.get("/audit/verify", headers=auth("auditor")).json()
    assert not v["ok"] and v["broken_at"] == 3 and "link" in v["reason"]


def test_failed_logins_and_uploads_are_audited(client, auth, fake_pipeline):
    client.post("/auth/login", json={"username": "reviewer", "password": "bad"})
    client.post("/cases", files=[("files", ("x.png", b"nope", "image/png"))], headers=auth("submitter"))
    actions = [e["action"] for e in client.get("/audit", headers=auth("auditor")).json()]
    assert "login_failed" in actions and "upload_rejected" in actions


# ── report, ops, policies, storage, redaction ────────────────────────────────────────────────────────
def test_case_report_pdf(client, auth, fake_pipeline):
    cid = upload(client, auth("submitter")).json()["case_id"]
    r = client.get(f"/cases/{cid}/report.pdf", headers=auth("reviewer"))
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and len(r.content) > 3000
    assert r.headers["content-type"] == "application/pdf" and cid in r.headers["content-disposition"]


def test_ops_summary(client, auth, fake_pipeline):
    fake_pipeline.decision = "APPROVE"
    upload(client, auth("submitter"))
    fake_pipeline.decision = "ESCALATE"
    upload(client, auth("submitter"))
    s = client.get("/ops/summary", headers=auth("auditor")).json()
    assert s["cases"] == 2 and s["stp_rate"] == 0.5 and s["open_reviews"] == 1
    assert s["business_impact"]["baseline_annual_cost_usd"] == 18_400_000


def test_policy_upload_validation(client, auth, fake_pipeline, monkeypatch):
    from medishield.api.routes import policies as pol
    queued = []
    monkeypatch.setattr(pol, "enqueue_policy", queued.append)
    bad = client.post("/policies", data={"plan": "gold"}, files={"file": ("p.pdf", io.BytesIO(b"not a pdf"), "application/pdf")}, headers=auth("admin"))
    assert bad.status_code == 415
    bad_plan = client.post("/policies", data={"plan": "Gold Plan!"}, files={"file": ("p.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}, headers=auth("admin"))
    assert bad_plan.status_code == 422
    ok = client.post("/policies", data={"plan": "platinum"}, files={"file": ("p.pdf", io.BytesIO(b"%PDF-1.4 stub"), "application/pdf")}, headers=auth("admin"))
    assert ok.status_code == 202 and ok.json()["status"] == "INGESTING" and queued == [ok.json()["id"]]


def test_healthz_is_public(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_local_storage_refuses_path_traversal(env):
    from medishield.storage.base import LocalStorage
    s = LocalStorage(env / "store")
    s.put("a/b.png", b"x")
    assert s.get("a/b.png") == b"x"
    with pytest.raises(ValueError):
        s.put("../escape.png", b"x")


def test_s3_storage_roundtrip(env):
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")
    with moto.mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="claims")
        from medishield.storage.base import S3Storage
        s = S3Storage("claims", client=client, cache_dir=env / "s3cache")
        assert not s.exists("cases/C1/doc.png")
        s.put("cases/C1/doc.png", b"pixels", "image/png")
        assert s.exists("cases/C1/doc.png") and s.get("cases/C1/doc.png") == b"pixels"
        assert s.local_path("cases/C1/doc.png").read_bytes() == b"pixels"


def test_phi_redaction():
    from medishield.api.security import redact
    msg = "member Christopher Harris I. DOB 04/25/1954 ssn 489-22-6881 policy MED-GLD-6770619 NPI-5610293847 Bearer abc.def.ghi"
    out = redact(msg)
    for leaked in ("Christopher", "04/25/1954", "489-22-6881", "6770619", "5610293847", "abc.def"):
        assert leaked not in out


def test_production_refuses_default_jwt_secret(monkeypatch):
    from medishield.config import get_settings
    monkeypatch.setenv("MEDISHIELD_ENV", "production")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        get_settings()
    get_settings.cache_clear()


def test_report_has_no_literal_markup(client, auth, fake_pipeline):
    import pypdfium2 as pdfium
    cid = upload(client, auth("submitter")).json()["case_id"]
    pdf = pdfium.PdfDocument(client.get(f"/cases/{cid}/report.pdf", headers=auth("reviewer")).content)
    text = "".join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
    assert cid in text and "<b>" not in text and "Hash-chain status" in text and "VERIFIED" in text


def test_timestamps_are_utc_aware(client, auth, fake_pipeline):
    """SQLite drops offsets; without an explicit 'Z' browsers would read UTC times as local time."""
    upload(client, auth("submitter"))
    case = client.get("/cases", headers=auth("reviewer")).json()[0]
    assert case["created_at"].endswith(("Z", "+00:00")) and case["sla_due"].endswith(("Z", "+00:00"))


def test_cost_kpis_use_uncached_cost(client, auth, fake_pipeline):
    """A replayed run spends $0, but the dashboard must show what a case costs without the cache."""
    cid = upload(client, auth("submitter")).json()["case_id"]
    c = client.get(f"/cases/{cid}", headers=auth("reviewer")).json()
    assert c["cold_cost_usd"] == 0.01 and c["agent_runs"][0]["cold_cost_usd"] == 0.01
    assert client.get("/ops/summary", headers=auth("auditor")).json()["avg_cost_usd_per_case"] == 0.01


def test_log_redaction_keeps_uvicorn_access_logs_working():
    """The access formatter unpacks exactly five arguments; the filter must redact them without changing the shape."""
    import logging

    from medishield.api.security import PHIFilter
    from uvicorn.logging import AccessFormatter

    jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhIn0.c2lnbmF0dXJl"
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1:5000", "GET", f"/ws/cases/CASE-1?token={jwt_like}", "1.1", 200), None)
    assert PHIFilter().filter(rec) and len(rec.args) == 5
    line = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(rec)
    assert jwt_like not in line and "token=[TOKEN]" in line and "200" in line


def test_rerun_starts_a_fresh_progress_log(client, auth, fake_pipeline):
    """After a reclassification the live graph must not be fed the previous run's events."""
    cid = upload(client, auth("submitter")).json()["case_id"]
    first = client.get(f"/cases/{cid}/events", headers=auth("submitter")).json()
    client.post(f"/cases/{cid}/documents/doc0/reclassify", headers=auth("reviewer"),
                json={"doc_type": "CLAIM_FORM", "reason_code": "CLASSIFICATION_ERROR"})
    second = client.get(f"/cases/{cid}/events", headers=auth("submitter")).json()
    assert [e["node"] for e in second] == [e["node"] for e in first]          # one run's worth, not two
    assert min(e["id"] for e in second) > max(e["id"] for e in first)


def test_ela_heatmap_only_for_jpeg(client, auth, fake_pipeline):
    import io as _io

    from PIL import Image as _Image
    buf = _io.BytesIO()
    _Image.new("RGB", (400, 300), "white").save(buf, format="JPEG", quality=85)
    r = client.post("/cases", files=[("files", ("scan.jpg", buf.getvalue(), "image/jpeg")), ("files", ("page.png", png_bytes(), "image/png"))],
                    headers=auth("submitter"))
    cid = r.json()["case_id"]
    ok = client.get(f"/cases/{cid}/documents/scan/ela", headers=auth("reviewer"))
    assert ok.status_code == 200 and ok.content.startswith(b"\x89PNG")
    assert client.get(f"/cases/{cid}/documents/page/ela", headers=auth("reviewer")).status_code == 404
    assert client.get(f"/cases/{cid}/documents/scan/ela", headers={}).status_code == 401


def test_old_databases_get_new_columns(env):
    import sqlite3

    from medishield.config import get_settings
    from medishield.db.session import get_engine, reset_engine

    path = get_settings().state_dir / "medishield.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE cases (id VARCHAR(32) PRIMARY KEY, submitted_by VARCHAR(64), status VARCHAR(16), "
                 "risk_score FLOAT, total_amount FLOAT, wall_ms FLOAT, cost_usd FLOAT)")
    conn.execute("INSERT INTO cases (id, submitted_by, status, risk_score, total_amount, wall_ms, cost_usd) "
                 "VALUES ('CASE-OLD', 'x', 'DECIDED', 0, 0, 0, 0)")
    conn.commit()
    conn.close()
    reset_engine()
    get_engine()
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(cases)")}
    assert {"cold_cost_usd", "thread_id", "decision"} <= cols
    from medishield.db.repo import SqlRepo
    from medishield.db.session import session_scope

    with session_scope() as s:                               # SQLite-specific: read through the SQL repo in either test mode
        assert SqlRepo(s).get_case("CASE-OLD").cold_cost_usd == 0.0


def test_auth_config_says_whether_demo_passwords_exist(client, monkeypatch):
    assert client.get("/auth/config").json() == {"demo_passwords": True}      # the test env seeds demo users


def test_eval_endpoint_returns_only_pipeline_runs(client, auth, tmp_path, monkeypatch):
    import json
    d = tmp_path / "evals"
    d.mkdir()
    (d / "official-dev.json").write_text(json.dumps({"ops": {}, "decision": {}, "classification": {}}))
    (d / "calibrator.json").write_text(json.dumps({"x": [0, 1]}))
    (d / "reranker.json").write_text(json.dumps([{"model": "m"}]))
    monkeypatch.setenv("MEDISHIELD_EVAL_DIR", str(d))
    assert list(client.get("/ops/eval", headers=auth("reviewer")).json()) == ["official-dev"]
