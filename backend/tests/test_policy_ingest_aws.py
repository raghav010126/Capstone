"""Policy upload on AWS, against moto (S3 + DynamoDB): the API stores the PDF in S3 and invokes the Docling Lambda, the Lambda
publishes the parsed index, and agent runtimes load it from S3 without Docling. Docling and the Lambda invoke are stubbed."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys

import boto3
import pytest
from moto import mock_aws

PDF = b"%PDF-1.4 diamond plan policy"
SHA = hashlib.sha256(PDF).hexdigest()


@pytest.fixture
def aws(env, monkeypatch):
    """AWS mode. Yields the list of ingest Lambda invocations."""
    for k, v in (("AWS_ACCESS_KEY_ID", "t"), ("AWS_SECRET_ACCESS_KEY", "t"), ("AWS_DEFAULT_REGION", "us-east-1"),
                 ("MEDISHIELD_DB", "dynamodb"), ("DYNAMO_TABLE", "t"), ("STORAGE_BACKEND", "s3"), ("S3_BUCKET", "docs"),
                 ("MEDISHIELD_QUEUE", "agentcore"), ("POLICY_INGEST_FUNCTION", "medishield-ingest"),
                 ("MEDISHIELD_CACHE", str(env / "cache"))):
        monkeypatch.setenv(k, v)
    invoked: list[dict] = []

    class FakeLambda:
        def invoke(self, **kw):
            invoked.append(kw)
            return {"StatusCode": 202}

    real = boto3.client
    monkeypatch.setattr(boto3, "client", lambda name, *a, **kw: FakeLambda() if name == "lambda" else real(name, *a, **kw))
    with mock_aws():
        from conftest import reset_runtime
        from medishield.db.dynamo import get_dynamo_repo

        reset_runtime()
        get_dynamo_repo().ensure_table()
        real("s3", region_name="us-east-1").create_bucket(Bucket="docs")
        yield invoked


def s3_keys(prefix: str) -> list[str]:
    return [o["Key"] for o in boto3.client("s3", region_name="us-east-1").list_objects_v2(Bucket="docs", Prefix=prefix)
            .get("Contents", [])]


def fake_docling(monkeypatch, calls: list | None = None, fail: Exception | None = None):
    """Stand-in for the Docling parse (``ingest_pdf``); ``load_or_ingest`` around it is the real one."""
    from medishield.rag import ingest
    from medishield.rag.exclusions import CptRange

    def parse(pdf, plan=None):
        if calls is not None:
            calls.append(pdf.name)
        if fail:
            raise fail
        plan = plan or ingest.plan_from_filename(pdf)
        return ingest.PolicyIndex(plan, "MED-DIA-2026", pdf.name,
                                  [ingest.Chunk(f"{plan}-000", plan, "4.1 Excluded CPT Code Ranges", "4.1", None, [3], "table",
                                                "| 17000-17999 | Cosmetic | S4(a) |")],
                                  [CptRange("17000", "17999", "Cosmetic", "S4(a)", "exclusion", plan, 3)])

    monkeypatch.setattr(ingest, "ingest_pdf", parse)


def policy(pid: int):
    from medishield.db.repo import repo_scope

    with repo_scope() as db:
        return db.get_policy(pid)


def test_upload_stores_the_pdf_in_s3_and_invokes_the_ingest_lambda(aws, client, auth, monkeypatch):
    from medishield.api.routes import policies as pol

    monkeypatch.setattr(pol, "docling_installed", lambda: False)           # like the API image
    r = client.post("/policies", data={"plan": "diamond"}, files={"file": ("d.pdf", io.BytesIO(PDF), "application/pdf")},
                    headers=auth("admin"))
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "INGESTING"
    assert aws == [{"FunctionName": "medishield-ingest", "InvocationType": "Event",
                    "Payload": json.dumps({"policy_id": r.json()["id"]}).encode()}]
    assert s3_keys("policies/") == [f"policies/diamond-{SHA[:12]}.pdf"]


def test_an_ingest_lambda_that_cannot_be_started_fails_the_policy(aws, client, auth, monkeypatch):
    from medishield.api.routes import policies as pol
    from medishield.db.repo import repo_scope
    from medishield.worker import queue

    def refuse(policy_id):
        raise RuntimeError("throttled")

    monkeypatch.setattr(pol, "docling_installed", lambda: False)
    monkeypatch.setattr(queue, "_invoke_ingest_lambda", refuse)
    r = client.post("/policies", data={"plan": "diamond"}, files={"file": ("d.pdf", io.BytesIO(PDF), "application/pdf")},
                    headers=auth("admin"))
    assert r.status_code == 503
    with repo_scope() as db:
        (p,) = db.list_policies()
    assert p.status == "FAILED" and "RuntimeError" in p.error


def test_ingest_lambda_parses_the_pdf_from_s3_and_publishes_the_index(aws, monkeypatch):
    from medishield import aws_ingest
    from medishield.config import get_settings
    from medishield.db.repo import repo_scope
    from medishield.services import policies

    calls: list[str] = []
    fake_docling(monkeypatch, calls)
    pid = policies.save_upload("diamond", "d.pdf", PDF, "admin")
    shutil.rmtree(get_settings().policy_upload_dir)                         # the Lambda is another machine: only S3 has the PDF
    assert aws_ingest.handler({"policy_id": pid}) == {"policy_id": pid, "status": "READY"}
    p = policy(pid)
    assert (p.product_code, p.chunk_count, p.error) == ("MED-DIA-2026", 1, None)
    assert [(r["start"], r["end"], r["plan"]) for r in p.ranges] == [("17000", "17999", "diamond")]
    (key,) = s3_keys("policies/index/")
    assert key == f"policies/index/diamond-{SHA[:12]}-{SHA[:16]}-v1.json"
    index = json.loads(boto3.client("s3", region_name="us-east-1").get_object(Bucket="docs", Key=key)["Body"].read())
    assert index["chunks"][0]["section_no"] == "4.1" and index["ranges"][0]["start"] == "17000"
    with repo_scope() as db:
        assert db.list_audit(case_id=None, action="policy_ingested", limit=5, offset=0)
    assert aws_ingest.handler({"policy_id": pid})["skipped"] and calls == [f"diamond-{SHA[:12]}.pdf"]   # no second parse


def test_ingest_lambda_marks_an_unparseable_policy_failed(aws, monkeypatch):
    from medishield import aws_ingest
    from medishield.services import policies

    fake_docling(monkeypatch, fail=ValueError("no text layer"))
    pid = policies.save_upload("diamond", "d.pdf", PDF, "admin")
    assert aws_ingest.handler({"policy_id": pid})["status"] == "FAILED"
    assert policy(pid).error == "ValueError: no text layer" and s3_keys("policies/index/") == []
    assert aws_ingest.handler({"policy_id": 999}) == {"policy_id": 999, "status": None, "skipped": True}


def test_runtimes_load_uploaded_policies_from_s3_without_docling(aws, monkeypatch):
    from medishield import aws_ingest
    from medishield.config import get_settings
    from medishield.db.repo import repo_scope
    from medishield.rag import ingest, retrieve
    from medishield.services import policies

    fake_docling(monkeypatch)
    aws_ingest.handler({"policy_id": policies.save_upload("diamond", "d.pdf", PDF, "admin")})
    with repo_scope() as db:                                                # READY, but its files are gone from S3: skipped
        ghost = db.add_policy("ghost", "g.pdf", "f" * 64, "admin")
        ghost.status = "READY"
        db.save_policy(ghost)
    s = get_settings()                                                      # a fresh agent session: empty disk, no Docling
    shutil.rmtree(s.policy_upload_dir)
    shutil.rmtree(s.cache_dir / "policy_index")
    monkeypatch.setitem(sys.modules, "docling", None)
    monkeypatch.setattr(ingest, "ingest_pdf", lambda *a, **kw: pytest.fail("a runtime must never parse a policy PDF"))
    built = []
    monkeypatch.setattr(retrieve, "PolicyStore", lambda indexes: built.append(indexes) or "store")
    monkeypatch.setattr(retrieve, "policy_pdfs", lambda root=None: [])
    retrieve.get_store.cache_clear()
    try:
        assert retrieve.get_store() == "store"
    finally:
        retrieve.get_store.cache_clear()
    (indexes,) = built
    assert [i.plan for i in indexes] == ["diamond"] and {c.plan for c in indexes[0].chunks} == {"diamond"}
    assert [r.label for r in indexes[0].ranges] == ["17000-17999"]


def test_agent_images_can_add_fetched_indexes_beside_the_baked_ones(tmp_path, monkeypatch):
    """The images link read-only baked caches into /tmp; the policy index folder must stay writable."""
    from medishield.aws_handlers import link_baked_caches

    baked, cache = tmp_path / "baked", tmp_path / "cache"
    (baked / "policy_index").mkdir(parents=True)
    (baked / "policy_index" / "gold.json").write_text("{}")
    (baked / "fastembed").mkdir()
    monkeypatch.setenv("BAKED_CACHE", str(baked))
    monkeypatch.setenv("MEDISHIELD_CACHE", str(cache))
    (cache / "policy_index").parent.mkdir()
    (cache / "policy_index").symlink_to(baked / "policy_index")          # what an earlier version of this code left behind
    link_baked_caches()
    link_baked_caches()                                                  # idempotent
    assert not (cache / "policy_index").is_symlink() and (cache / "policy_index" / "gold.json").is_symlink()
    assert (cache / "fastembed").is_symlink()
    (cache / "policy_index" / "diamond.json").write_text("{}")
    assert not (baked / "policy_index" / "diamond.json").exists()


def test_local_mode_is_unchanged(env, client, auth, monkeypatch):
    """No S3 (even with an ingest function configured): the local disk and the local worker, as before."""
    from medishield.api.routes import policies as pol
    from medishield.config import get_settings
    from medishield.db.repo import repo_scope
    from medishield.services import policies, policy_s3

    monkeypatch.setenv("POLICY_INGEST_FUNCTION", "medishield-ingest")
    get_settings.cache_clear()
    monkeypatch.setattr(policy_s3, "_storage", lambda: pytest.fail("local mode must not use S3"))
    assert not policy_s3.lambda_ingest()
    old = policies.save_upload("diamond", "a.pdf", PDF, "admin")
    new = policies.save_upload("diamond", "b.pdf", PDF + b" v2", "admin")
    with repo_scope() as db:
        for pid in (old, new):
            p = db.get_policy(pid)
            p.status = "READY"
            db.save_policy(p)
    assert policies.uploaded_policy_paths() == [policies.policy_path(policy(new))]
    assert policies.policy_path(policy(new)).read_bytes() == PDF + b" v2"
    monkeypatch.setattr(pol, "docling_installed", lambda: False)
    r = client.post("/policies", data={"plan": "diamond"}, files={"file": ("d.pdf", io.BytesIO(PDF), "application/pdf")},
                    headers=auth("admin"))
    assert r.status_code == 501                                             # no parser and no ingest Lambda
