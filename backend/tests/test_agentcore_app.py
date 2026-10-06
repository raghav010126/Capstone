"""The AgentCore Runtime contract, exercised in-process: POST /invocations returns at once, /ping reports HealthyBusy while
the case is processed in the background, and the API hands jobs to the runtime through InvokeAgentRuntime."""

from __future__ import annotations

import io
import json
import threading
import time

import pytest
from conftest import auth as _auth  # noqa: F401  (fixture re-export)
from conftest import png_bytes
from starlette.testclient import TestClient


@pytest.fixture
def runtime(env, fake_pipeline, monkeypatch):
    from medishield import agentcore_app

    monkeypatch.setattr(agentcore_app, "ROLE", "pipeline")
    monkeypatch.setattr(agentcore_app, "_init", lambda: None)
    return agentcore_app


def _make_case() -> str:
    from medishield.api.security import Principal, Role
    from medishield.db.repo import repo_scope
    from medishield.services import cases

    with repo_scope() as db:
        case, _w, _c = cases.create_case(db, Principal("submitter", Role.SUBMITTER, "S"), [("a.png", png_bytes())], None)
        return case.id


def test_invocation_returns_at_once_and_ping_tracks_the_background_work(runtime, fake_pipeline, monkeypatch):
    from medishield.services import cases

    gate = threading.Event()
    real = cases.process_case
    monkeypatch.setattr(cases, "process_case", lambda cid: (gate.wait(5), real(cid)))
    case_id = _make_case()
    client = TestClient(runtime.app)
    r = client.post("/invocations", json={"task": "process_case", "case_id": case_id})
    assert r.status_code == 200 and r.json() == {"accepted": True, "task": "process_case", "case_id": case_id}
    assert client.get("/ping").json()["status"] == "HealthyBusy"          # session must stay alive while the case runs
    gate.set()
    for _ in range(100):
        if client.get("/ping").json()["status"] == "Healthy":
            break
        time.sleep(0.05)
    assert client.get("/ping").json()["status"] == "Healthy"
    from medishield.db.repo import repo_scope

    with repo_scope() as db:
        assert db.get_case(case_id).status in ("IN_REVIEW", "DECIDED")


def test_unknown_task_is_refused(runtime):
    r = TestClient(runtime.app).post("/invocations", json={"task": "drop_tables"})
    assert "unsupported task" in r.json()["error"]


def test_api_hands_cases_to_the_pipeline_runtime(env, monkeypatch):
    from medishield.config import get_settings
    from medishield.worker import queue

    monkeypatch.setenv("MEDISHIELD_QUEUE", "agentcore")
    monkeypatch.setenv("PIPELINE_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:111122223333:runtime/medishield_pipeline-x")
    get_settings.cache_clear()
    calls = []

    class FakeClient:
        def invoke_agent_runtime(self, **kw):
            calls.append(kw)
            return {"response": io.BytesIO(json.dumps({"accepted": True}).encode())}

    import boto3

    monkeypatch.setattr(boto3, "client", lambda name, **k: FakeClient() if name == "bedrock-agentcore" else None)
    queue.enqueue_case("CASE-1")
    kw = calls[0]
    assert kw["agentRuntimeArn"].endswith("medishield_pipeline-x") and len(kw["runtimeSessionId"]) >= 33
    assert json.loads(kw["payload"]) == {"task": "process_case", "case_id": "CASE-1"}
    get_settings.cache_clear()
