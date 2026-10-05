"""API test harness: every test gets a fresh state dir (database, uploads, queue, checkpoints), inline task
execution, and - unless it asks for the real pipeline - a fake pipeline so no model is ever called."""

from __future__ import annotations

import io
import itertools

import pytest
from fastapi.testclient import TestClient
from medishield.schemas import (
    Classification,
    DocType,
    ExtractionResult,
    FraudResult,
    QualityMetrics,
    RiskLevel,
)
from PIL import Image

PASSWORDS = {u: f"{u}-demo" for u in ("submitter", "reviewer", "senior", "auditor", "admin")}


def reset_runtime() -> None:
    from medishield import pipeline
    from medishield.api.security import limiter
    from medishield.config import get_settings
    from medishield.db.session import reset_engine
    from medishield.records import get_records
    from medishield.storage.base import get_storage
    from medishield.worker.queue import get_huey, tasks

    get_settings.cache_clear()
    get_storage.cache_clear()
    tasks.cache_clear()
    get_huey.cache_clear()
    reset_engine()
    pipeline.reset_graphs()
    limiter.reset()
    from medishield.llm import cost

    cost._ledger = None
    get_records().reset_processed()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDISHIELD_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MEDISHIELD_QUEUE_IMMEDIATE", "1")
    monkeypatch.setenv("MEDISHIELD_DEMO_USERS", "1")
    monkeypatch.setenv("MEDISHIELD_LLM_OFFLINE", "1")
    monkeypatch.setenv("MEDISHIELD_ENV", "dev")
    monkeypatch.setenv("MEDISHIELD_LEDGER_PATH", str(tmp_path / "spend.jsonl"))   # never touch the real spend ledger
    monkeypatch.setenv("BCRYPT_ROUNDS", "4")                       # fast hashing in tests only
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    reset_runtime()
    yield tmp_path
    reset_runtime()


def png_bytes(color=(255, 255, 255), size=(400, 300), text_seed: int = 0) -> bytes:
    """A small valid PNG; ``text_seed`` makes distinct files distinct."""
    im = Image.new("RGB", size, color)
    for i in range(20):
        im.putpixel((10 + i + text_seed, 10 + text_seed), (0, 0, 0))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


_counter = itertools.count(1)


def fake_state(doc_ids: list[str], decision: str = "ESCALATE", amount: float = 500.0, risk: float = 0.6) -> dict:
    """What ``pipeline.run_case_stream`` returns for a case, without running any model."""
    docs, perception, specialists = [], {}, {}
    for i, d in enumerate(doc_ids):
        is_claim = i == 0
        dtype = DocType.CLAIM_FORM if is_claim else DocType.ID_DOCUMENT
        values = ({"claim_number": f"CLM-2024-{next(_counter):05d}", "total_charge": amount, "service_date": "2025-11-09",
                   "policy_number": "MED-GLD-0000000", "patient_name": "Test Patient", "patient_dob": "01/01/1980",
                   "service_lines": [], "icd_codes": []} if is_claim else {"name_on_id": "Test Patient"})
        cls = Classification(doc_type=dtype, confidence=0.97, routing_tags=[], llm_doc_type=dtype, llm_self_confidence=0.97,
                             keyword_doc_type=dtype, keyword_margin=0.9, reason="test")
        ext = ExtractionResult(doc_type=dtype, fields=[], values=values, raw_text="", bounding_boxes=[],
                               grounding_rate=1.0, support_rate=1.0, confidence=0.95)
        q = QualityMetrics(width=400, height=300, sharpness=900, blank=False, blur_suspected=False,
                           ocr_mean_score=0.99, ocr_lines=10, quality_score=0.95)
        perception[d] = {"classification": cls.model_dump(mode="json"), "quality": q.model_dump(),
                         "extraction": ext.model_dump(mode="json"), "image_hash": f"{i:016x}", "failed": []}
        specialists[d] = {}
        docs.append({"doc_id": d, "doc_type": dtype.value, "decision": decision, "confidence": 0.8,
                     "rule_id": "R3_fraud_or_low_confidence", "reasons": ["test"], "justification": "because"})
    fraud = FraudResult(fraud_score=risk, per_doc_score={d: risk for d in doc_ids}, anomalies=[], risk_level=RiskLevel.HIGH,
                        narrative="n")
    return {"decision": {"case_id": "X", "decision": decision, "confidence": 0.8, "documents": docs,
                         "agent_summaries": {"classifier": "test"}, "justification": "test justification"},
            "perception": perception, "specialists": specialists, "fraud": fraud.model_dump(mode="json"),
            "runs": [{"agent": "classifier", "model": "claude-sonnet-5-5", "retried_with": None, "input_tokens": 10,
                      "output_tokens": 5, "cost_usd": 0.01, "cold_cost_usd": 0.01, "latency_ms": 5.0, "llm_calls": 1,
                      "cache_hits": 0}]}


@pytest.fixture
def fake_pipeline(env, monkeypatch):
    """Replace the graph with a stub. ``fake_pipeline.next`` configures the next case's outcome."""
    from medishield import pipeline

    class Fake:
        decision, amount, risk, resumed, fail = "ESCALATE", 500.0, 0.6, [], None

    def run(case_id, paths, thread_id, on_event, forced_types=None, hitl=True):
        if Fake.fail:
            raise Fake.fail
        for ev in ({"node": "perceive", "status": "ok", "doc_id": paths[0][0]}, {"node": "decided", "status": Fake.decision}):
            on_event(ev)
        return {"values": fake_state([d for d, _ in paths], Fake.decision, Fake.amount, Fake.risk),
                "paused": Fake.decision == "ESCALATE", "wall_ms": 12.0}

    monkeypatch.setattr(pipeline, "run_case_stream", run)
    monkeypatch.setattr(pipeline, "resume_case", lambda tid, res, cb: Fake.resumed.append((tid, res)) or {"values": {}, "paused": False})
    Fake.resumed = []
    Fake.fail = None
    yield Fake


@pytest.fixture
def client(env, monkeypatch):
    from medishield.api import main

    monkeypatch.setattr(main, "_warm", lambda: None)          # don't build the policy store in unit tests
    with TestClient(main.create_app()) as c:
        yield c


def login(client: TestClient, user: str) -> dict:
    r = client.post("/auth/login", json={"username": user, "password": PASSWORDS[user]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth(client):
    cache: dict[str, dict] = {}

    def get(user: str) -> dict:
        if user not in cache:
            cache[user] = login(client, user)
        return cache[user]
    return get


def upload(client, headers, n: int = 2, **kw):
    files = [("files", (f"doc{i}.png", png_bytes(text_seed=i), "image/png")) for i in range(n)]
    return client.post("/cases", files=files, headers=headers, **kw)
