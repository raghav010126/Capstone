"""DynamoDB repo behaviour that the shared API suite does not reach (run under moto; no AWS account involved)."""

from __future__ import annotations

import threading

import pytest
from medishield.db import audit
from medishield.db.dynamo import DynamoRepo
from medishield.db.models import Case, Document
from moto import mock_aws


@pytest.fixture
def repo(monkeypatch):
    for k, v in (("AWS_ACCESS_KEY_ID", "t"), ("AWS_SECRET_ACCESS_KEY", "t")):
        monkeypatch.setenv(k, v)
    with mock_aws():
        r = DynamoRepo("t", "us-east-1")
        r.ensure_table()
        yield r


def make_case(cid="CASE-1", key=None, n=2):
    c = Case(id=cid, submitted_by="u", idempotency_key=key, status="RECEIVED")
    for i in range(n):
        c.documents.append(Document(doc_id=f"d{i}", position=i, filename="f.png", storage_key=f"k{i}", media_type="image/png",
                                    size_bytes=10, sha256="ab" * 32, page=1))
    return c


def test_case_round_trip_keeps_json_and_floats(repo):
    c, created = repo.add_case(make_case())
    assert created
    c.decision, c.fraud, c.total_amount = {"decision": "APPROVE", "n": [1, 2.5]}, {"fraud_score": 0.1}, 1234.56
    c.documents[0].extraction = {"fields": [], "values": {"x": 1.5}, "raw_text": "big", "bounding_boxes": [[1, 2, 3, 4]]}
    repo.save_document(c.documents[0])
    repo.save_case(c)
    got = repo.get_case("CASE-1")
    assert got.decision == {"decision": "APPROVE", "n": [1, 2.5]} and got.total_amount == 1234.56
    assert [d.doc_id for d in got.documents] == ["d0", "d1"]
    assert got.documents[0].extraction == {"fields": [], "values": {"x": 1.5}}        # heavy keys dropped
    assert got.created_at.tzinfo is not None


def test_idempotency_key_returns_the_first_case(repo):
    first, created1 = repo.add_case(make_case("CASE-A", key="k1"))
    again, created2 = repo.add_case(make_case("CASE-B", key="k1"))
    assert created1 and not created2 and again.id == first.id
    assert repo.get_case("CASE-B") is None


def test_list_view_has_stubs_and_filters(repo):
    a, _ = repo.add_case(make_case("CASE-1"))
    a.status, a.ai_decision, a.decision = "DECIDED", "APPROVE", {"big": "x" * 100}
    repo.save_case(a)
    repo.add_case(make_case("CASE-2"))
    rows = repo.list_cases(status="decided")
    assert [r.id for r in rows] == ["CASE-1"] and len(rows[0].documents) == 2 and rows[0].decision is None
    assert [r.id for r in repo.list_cases()] == ["CASE-2", "CASE-1"]                    # newest first
    assert [r.id for r in repo.list_cases(decision="approve")] == ["CASE-1"]


def test_events_are_ordered_and_resumable(repo):
    for i in range(5):
        repo.add_event("CASE-1", {"node": f"n{i}", "status": "ok", "extra": i})
    evs = repo.events_after("CASE-1", 0)
    assert [e.node for e in evs] == [f"n{i}" for i in range(5)] and evs[0].payload == {"extra": 0}
    assert [e.node for e in repo.events_after("CASE-1", evs[2].id)] == ["n3", "n4"]
    repo.clear_events("CASE-1")
    assert repo.events_after("CASE-1", 0) == []


def test_concurrent_audit_appends_form_one_unbroken_chain(repo, monkeypatch):
    # DynamoDB evaluates a ConditionExpression and writes as one atomic step; moto checks and writes separately with no lock,
    # so two threads can both "win" the same sequence number (flaky on slow CI runners). Restore DynamoDB's guarantee here:
    # the threads still collide on sequence numbers, so the append's re-read-and-relink retry is what keeps the chain whole.
    from moto.dynamodb.models import DynamoDBBackend

    lock, put = threading.Lock(), DynamoDBBackend.put_item

    def atomic_put(self, *args, **kwargs):
        with lock:
            return put(self, *args, **kwargs)

    monkeypatch.setattr(DynamoDBBackend, "put_item", atomic_put)

    def work(n):
        for i in range(8):
            audit.append(repo, f"actor{n}", "act", "CASE-1", {"i": i})

    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    v = audit.verify_chain(repo)
    assert v["ok"] and v["length"] == 32
    assert len(repo.audit_for_case("CASE-1")) == 32 and len(repo.list_audit(case_id=None, action="act", limit=10, offset=0)) == 10


def test_override_and_policy_ids_are_unique(repo):
    from medishield.db.models import Override

    ids = {repo.add_override(Override(case_id="C", requested_by="u", decision="APPROVE", reason_code="OTHER")).id for _ in range(5)}
    assert ids == {1, 2, 3, 4, 5}
    assert repo.pending_override("C").id == 1
    assert repo.get_policy(repo.add_policy("gold", "g.pdf", "0" * 64, "u").id).plan == "gold"


def test_oversized_item_is_refused(repo):
    c = make_case()
    c.documents[0].extraction = {"fields": ["x" * 1000] * 500}
    with pytest.raises(ValueError, match="400 KB"):
        repo.add_case(c)
