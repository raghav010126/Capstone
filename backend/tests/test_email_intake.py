"""Email intake: the parser, POST /intake/email, and the SES inbound Lambda handler (moto S3 + DynamoDB, queue stubbed)."""

from __future__ import annotations

import io
import json
from email.message import EmailMessage

import boto3
import pytest
from conftest import png_bytes
from medishield.api.uploads import UploadError
from medishield.intake.email import parse
from moto import mock_aws
from PIL import Image

SAM = "Sam Patient <Sam.Patient@Clinic.example>"
SENDERS = json.dumps({"sam.patient@clinic.example": "submitter", "rita@clinic.example": "reviewer"})


def pdf_bytes(pages: int = 1) -> bytes:
    ims = [Image.new("RGB", (600, 800), "white") for _ in range(pages)]
    buf = io.BytesIO()
    ims[0].save(buf, format="PDF", save_all=True, append_images=ims[1:])
    return buf.getvalue()


def eml(sender: str = SAM, attachments=(("claim.pdf", None), ("id.png", None)), logo: bool = True,
        message_id: str | None = "<c4f1e2@mail.clinic.example>", extra=()) -> bytes:
    """A message as a mail client writes it: text + HTML body (with an inline logo), then the attachments."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "intake@claims.example"
    msg["Subject"] = "Claim for Sam Patient"
    if message_id:
        msg["Message-ID"] = message_id
    msg.set_content("Please find my claim attached.")
    msg.add_alternative('<p>Please find my claim attached.</p><img src="cid:logo">', subtype="html")
    if logo:
        msg.get_payload()[1].add_related(png_bytes(size=(120, 40)), "image", "png", cid="<logo>", filename="logo.png",
                                         disposition="inline")
    for name, data in attachments:
        if data is None:
            data = pdf_bytes() if name.endswith(".pdf") else png_bytes(text_seed=len(name))
        maintype, subtype = ("application", "pdf") if name.endswith(".pdf") else ("image", "png")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    for name, data, maintype, subtype in extra:
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()


# ── parser ───────────────────────────────────────────────────────────────────────────────────────────
def test_parser_keeps_pdf_and_png_and_skips_body_and_inline_logo(env):
    p = parse(eml())
    assert [name for name, _ in p.attachments] == ["claim.pdf", "id.png"]
    assert p.attachments[0][1].startswith(b"%PDF-") and p.attachments[1][1].startswith(b"\x89PNG")
    assert p.sender == "sam.patient@clinic.example" and p.sender_domain == "clinic.example"
    assert p.subject == "Claim for Sam Patient" and p.message_id == "c4f1e2@mail.clinic.example"
    assert p.skipped == ["logo.png: small inline image (logo or signature); skipped"]
    assert p.idempotency_key.startswith("email:") and len(p.idempotency_key) <= 128


def test_parser_keeps_a_large_inline_photo(env):
    """Phone mail apps put photos inline: only *small* inline images are treated as logos."""
    assert [n for n, _ in parse(eml(), min_inline_image_bytes=100).attachments] == ["logo.png", "claim.pdf", "id.png"]


def test_parser_message_without_attachments(env):
    p = parse(eml(attachments=(), logo=False))
    assert p.attachments == [] and p.skipped == []


def test_parser_rejects_an_oversized_message(env):
    with pytest.raises(UploadError) as e:
        parse(eml(), max_bytes=10_000)
    assert e.value.status == 413


def test_parser_skips_non_document_types_but_sniffs_unlabelled_documents(env):
    raw = eml(attachments=(), logo=False, extra=(
        ("notes.txt", b"call me", "text", "plain"),
        ("form.docx", b"PK\x03\x04 office", "application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("anim.gif", b"GIF89a....", "image", "gif"),
        ("scan", pdf_bytes(), "application", "octet-stream"),               # no extension, no type: the magic bytes say PDF
    ))
    p = parse(raw)
    assert [n for n, _ in p.attachments] == ["scan"]
    assert len(p.skipped) == 3 and all("not a PDF, PNG, JPEG or TIFF document" in s for s in p.skipped)


def test_parser_requires_exactly_one_from_address(env):
    for bad in ("", "a@x.example, b@y.example", "not an address"):
        with pytest.raises(UploadError) as e:
            parse(eml(sender=bad))
        assert e.value.status == 422
    for good in ('"Patient, Sam" <SAM@x.example>', "=?utf-8?b?U8OkbSBQw6R0aWVudA==?= <sam@x.example>", "sam@x.example (Sam)"):
        assert parse(f"From: {good}\r\n\r\nhi\r\n".encode()).sender == "sam@x.example"


def test_parser_rejects_absurd_mime_nesting(env):
    raw = b"From: sam@x.example\r\nContent-Type: multipart/mixed; boundary=b0\r\n\r\n" + b"".join(
        f"--b{i}\r\nContent-Type: multipart/mixed; boundary=b{i + 1}\r\n\r\n".encode() for i in range(3000))
    with pytest.raises(UploadError) as e:
        parse(raw)
    assert e.value.status == 422


def test_message_without_message_id_is_keyed_on_its_content(env):
    raw = eml(message_id=None)
    assert parse(raw).message_id == "" and parse(raw).idempotency_key == parse(raw).idempotency_key
    assert parse(raw).idempotency_key != parse(eml(message_id=None)).idempotency_key       # a new message (new MIME boundaries)
    assert parse(eml()).idempotency_key == parse(eml()).idempotency_key                    # same Message-ID, same key


# ── POST /intake/email ──────────────────────────────────────────────────────────────────────────────
def audit_rows(client, auth, action):
    return client.get("/audit", params={"action": action, "limit": 50}, headers=auth("auditor")).json()


def test_endpoint_creates_case_and_is_idempotent_on_message_id(client, auth, fake_pipeline, monkeypatch):
    monkeypatch.setenv("INTAKE_SENDERS", SENDERS)
    sub = auth("submitter")
    r = client.post("/intake/email", content=eml(), headers={**sub, "Content-Type": "message/rfc822"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["documents"] == ["claim", "id"] and not body["idempotent_replay"]
    assert any("logo.png" in w for w in body["warnings"])
    case = client.get(f"/cases/{body['case_id']}", headers=sub).json()
    assert case["submitted_by"] == "submitter" and case["status"] in ("IN_REVIEW", "DECIDED")   # queued and processed

    again = client.post("/intake/email", files={"file": ("claim.eml", eml(), "message/rfc822")}, headers=sub)
    assert again.status_code == 200 and again.json()["case_id"] == body["case_id"] and again.json()["idempotent_replay"]
    assert len(client.get("/cases", headers=sub).json()) == 1

    rows = audit_rows(client, auth, "case_created_by_email")
    assert len(rows) == 1 and rows[0]["case_id"] == body["case_id"]
    assert rows[0]["detail"]["sender_domain"] == "clinic.example" and rows[0]["detail"]["channel"] == "api"
    assert "sam" not in json.dumps(rows[0]["detail"]).lower()


def test_endpoint_rejects_unknown_sender_and_audits_only_the_domain(client, auth, fake_pipeline, monkeypatch):
    monkeypatch.setenv("INTAKE_SENDERS", SENDERS)
    r = client.post("/intake/email", content=eml(sender="Mallory <mallory@evil.example>"),
                    headers={**auth("submitter"), "Content-Type": "message/rfc822"})
    assert r.status_code == 403
    assert client.get("/cases", headers=auth("admin")).json() == []
    rows = audit_rows(client, auth, "email_rejected")
    assert len(rows) == 1 and rows[0]["detail"]["sender_domain"] == "evil.example"
    assert "mallory" not in json.dumps(rows[0]["detail"]).lower()


def test_no_allow_list_means_no_email_is_processed(client, auth, fake_pipeline, monkeypatch):
    monkeypatch.delenv("INTAKE_SENDERS", raising=False)
    r = client.post("/intake/email", content=eml(), headers={**auth("admin"), "Content-Type": "message/rfc822"})
    assert r.status_code == 403
    monkeypatch.setenv("INTAKE_SENDERS", "{not json")
    r = client.post("/intake/email", content=eml(), headers={**auth("admin"), "Content-Type": "message/rfc822"})
    assert r.status_code == 403


def test_submitters_only_send_their_own_mail_and_staff_can_act_as_a_gateway(client, auth, fake_pipeline, monkeypatch):
    monkeypatch.setenv("INTAKE_SENDERS", SENDERS)
    rita = eml(sender="rita@clinic.example")
    assert client.post("/intake/email", content=rita, headers={**auth("submitter"), "Content-Type": "message/rfc822"}).status_code == 403
    r = client.post("/intake/email", content=rita, headers={**auth("admin"), "Content-Type": "message/rfc822"})
    assert r.status_code == 202
    assert client.get(f"/cases/{r.json()['case_id']}", headers=auth("admin")).json()["submitted_by"] == "admin"
    assert client.post("/intake/email", content=eml(), headers={**auth("auditor"), "Content-Type": "message/rfc822"}).status_code == 403


def test_endpoint_applies_the_upload_validation(client, auth, fake_pipeline, monkeypatch):
    monkeypatch.setenv("INTAKE_SENDERS", SENDERS)
    sub = {**auth("submitter"), "Content-Type": "message/rfc822"}
    disguised = eml(attachments=(("claim.pdf", b"MZ\x90\x00" + b"\x00" * 200),), message_id="<x1@clinic.example>")
    assert client.post("/intake/email", content=disguised, headers=sub).status_code == 415
    empty = eml(attachments=(), message_id="<x2@clinic.example>")
    assert client.post("/intake/email", content=empty, headers=sub).status_code == 422
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "2000")
    from conftest import reset_runtime
    reset_runtime()
    big = eml(attachments=(("claim.pdf", None),), message_id="<x3@clinic.example>")
    assert client.post("/intake/email", content=big, headers=sub).status_code == 413
    reasons = [row["detail"]["reason"] for row in audit_rows(client, auth, "email_rejected")]
    assert len(reasons) == 3 and client.get("/cases", headers=auth("admin")).json() == []


# ── SES inbound (Lambda) ────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def ses(env, monkeypatch, fake_pipeline):
    for k, v in (("AWS_ACCESS_KEY_ID", "t"), ("AWS_SECRET_ACCESS_KEY", "t"), ("AWS_DEFAULT_REGION", "us-east-1"),
                 ("MEDISHIELD_DB", "dynamodb"), ("DYNAMO_TABLE", "t"), ("STORAGE_BACKEND", "s3"), ("S3_BUCKET", "docs"),
                 ("INTAKE_SENDERS", SENDERS)):
        monkeypatch.setenv(k, v)
    with mock_aws():
        from conftest import reset_runtime
        from medishield import aws_handlers
        from medishield.api.main import seed_users
        from medishield.db.dynamo import get_dynamo_repo
        from medishield.worker import queue

        reset_runtime()
        aws_handlers._ready = False
        get_dynamo_repo().ensure_table()
        seed_users()
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="docs")
        queued: list[str] = []
        monkeypatch.setattr(queue, "enqueue_case", queued.append)
        yield s3, queued


def ses_event(ses_id: str, sender: str = SAM, **verdicts) -> dict:
    status = {"spf": "PASS", "dkim": "PASS", "dmarc": "PASS", "spam": "PASS", "virus": "PASS", **verdicts}
    return {"Records": [{"eventSource": "aws:ses", "eventVersion": "1.0", "ses": {
        "mail": {"messageId": ses_id, "source": "bounces@clinic.example", "destination": ["intake@claims.example"],
                 "commonHeaders": {"from": [sender], "to": ["intake@claims.example"], "subject": "Claim"}},
        "receipt": {"recipients": ["intake@claims.example"], **{f"{k}Verdict": {"status": v} for k, v in status.items()},
                    "action": {"type": "Lambda", "invocationType": "Event"}}}}]}


def stored(s3, key: str) -> bool:
    return bool(s3.list_objects_v2(Bucket="docs", Prefix=key).get("Contents"))


def audit_actions() -> list:
    from medishield.db.repo import repo_scope

    with repo_scope() as db:
        return [(e.action, e.actor, e.detail) for e in db.iter_audit()]


def test_ses_mapped_sender_creates_case_and_enqueues(ses):
    from medishield.db.repo import repo_scope
    from medishield.intake.ses import handler

    s3, queued = ses
    s3.put_object(Bucket="docs", Key="inbound/m1", Body=eml())
    out = handler(ses_event("m1"), None)["results"][0]
    assert out["status"] == "created" and queued == [out["case_id"]]
    with repo_scope() as db:
        case = db.get_case(out["case_id"])
        assert case.submitted_by == "submitter" and [d.doc_id for d in case.documents] == ["claim", "id"]
    assert not stored(s3, "inbound/m1")                                   # raw mail is not kept once the case exists
    events = audit_actions()
    assert ("case_created_by_email", "submitter") in [(a, u) for a, u, _ in events]
    assert next(d for a, _, d in events if a == "case_created_by_email")["channel"] == "ses"

    assert handler(ses_event("m1"), None)["results"][0]["status"] == "gone"   # at-least-once re-delivery
    s3.put_object(Bucket="docs", Key="inbound/m1b", Body=eml())                # the same Message-ID delivered again
    again = handler(ses_event("m1b"), None)["results"][0]
    assert again == {"status": "duplicate", "case_id": out["case_id"]} and queued == [out["case_id"]]


@pytest.mark.parametrize("verdict", ["dkim", "spf", "dmarc", "virus", "spam"])
def test_ses_failed_verdict_is_rejected_and_never_processed(ses, verdict):
    from medishield.intake.ses import handler

    s3, queued = ses
    s3.put_object(Bucket="docs", Key="inbound/m2", Body=eml())
    out = handler(ses_event("m2", **{verdict: "FAIL"}), None)["results"][0]
    assert out["status"] == "rejected" and f"{verdict}=FAIL" in out["reason"] and queued == []
    assert not stored(s3, "inbound/m2")
    # unauthenticated internet mail is logged, not written to the audit chain (it must not be able to grow it)
    assert [a for a, _, _d in audit_actions() if a == "email_rejected"] == []
    assert not any(a == "case_created" for a, _, _ in audit_actions())


def test_ses_disabled_scanning_is_not_a_failure_but_gray_is(ses):
    from medishield.intake.ses import handler

    s3, _queued = ses
    s3.put_object(Bucket="docs", Key="inbound/m3", Body=eml())
    assert handler(ses_event("m3", spam="DISABLED", virus="DISABLED"), None)["results"][0]["status"] == "created"
    s3.put_object(Bucket="docs", Key="inbound/m4", Body=eml(message_id="<other@clinic.example>"))
    assert handler(ses_event("m4", dmarc="GRAY"), None)["results"][0]["status"] == "rejected"


def test_ses_unknown_sender_and_forged_from_are_rejected(ses):
    from medishield.intake.ses import handler

    s3, queued = ses
    s3.put_object(Bucket="docs", Key="inbound/m5", Body=eml(sender="mallory@evil.example"))
    out = handler(ses_event("m5", sender="mallory@evil.example"), None)["results"][0]
    assert out["status"] == "rejected" and "allow-list" in out["reason"]
    s3.put_object(Bucket="docs", Key="inbound/m6", Body=eml(sender="mallory@evil.example"))
    out = handler(ses_event("m6"), None)["results"][0]                      # SES evaluated Sam; the stored message says otherwise
    assert out["status"] == "rejected" and queued == []
    assert [a for a, _, _d in audit_actions() if a == "email_rejected"] == []   # logged, not audited (unauthenticated)


def test_template_email_resources_are_optional_and_use_a_real_handler():
    """No domain = nothing created; the function's command names a handler that exists in the image's package."""
    import importlib
    from pathlib import Path

    import yaml

    class CfnLoader(yaml.SafeLoader):
        pass

    def tag(loader, suffix, node):                                # !Ref, !Sub, !If ... -> {"Ref": ...}
        if isinstance(node, yaml.ScalarNode):
            return {suffix: loader.construct_scalar(node)}
        if isinstance(node, yaml.SequenceNode):
            return {suffix: loader.construct_sequence(node, deep=True)}
        return {suffix: loader.construct_mapping(node, deep=True)}

    CfnLoader.add_multi_constructor("!", tag)
    t = yaml.load((Path(__file__).resolve().parents[2] / "infra" / "template.yaml").read_text(), Loader=CfnLoader)
    assert t["Parameters"]["InboundEmailDomain"]["Default"] == ""
    email = {n: r for n, r in t["Resources"].items() if r.get("Condition") == "HasInboundEmail"}
    assert {r["Type"] for r in email.values()} >= {"AWS::SES::ReceiptRuleSet", "AWS::SES::ReceiptRule", "AWS::Lambda::Function"}
    module, func = email["EmailFunction"]["Properties"]["ImageConfig"]["Command"][0].rsplit(".", 1)
    assert callable(getattr(importlib.import_module(module), func))
    assert email["EmailLogs"]["Properties"]["RetentionInDays"] == 7
