"""The LLM judge fails closed, and passage texts reach the evaluation only when it asks for them (offline: no model calls)."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_judge
from medishield.api.security import Principal, Role
from medishield.chat import service
from medishield.chat.sources import Passage

ROW = {"category": "policy", "role": "submitter", "question": "Is CPT 17000 covered on the Gold plan?", "expect_blocked": False,
       "facts": [["not covered"], ["17000"]], "forbid": []}


def verdict(scores=(5, 5, 5, 5), overall=True):
    c = [chat_judge.Criterion(score=s, reason="r") for s in scores]
    return chat_judge.JudgeVerdict(accuracy=c[0], completeness=c[1], refusal=c[2], citations=c[3], overall_pass=overall,
                                   justification="because")


def fake_structured(result=None, error=None):
    def call(step, system, parts, out, **kw):
        assert step == "chat_judge" and out is chat_judge.JudgeVerdict
        if error:
            raise error
        return NS(parsed=result, cost_usd=0.01, cold_cost_usd=0.01, cached=False)
    return call


@pytest.fixture
def patch_llm(monkeypatch):
    from medishield import llm

    def use(**kw):
        monkeypatch.setattr(llm, "structured", fake_structured(**kw))
    return use


def test_a_clean_verdict_passes(patch_llm):
    patch_llm(result=verdict())
    out = chat_judge.judge(ROW, "**Not covered** [1]", ["table 4.1: 17000-17999 excluded"])
    assert out["ok"] and out["scores"]["accuracy"] == 5 and out["justification"] == "because"


@pytest.mark.parametrize("v", [verdict(overall=False), verdict(scores=(2, 5, 5, 5)), verdict(scores=(5, 5, 5, 1))])
def test_a_negative_or_low_scoring_verdict_fails(patch_llm, v):
    patch_llm(result=v)
    assert not chat_judge.judge(ROW, "answer", [])["ok"]


@pytest.mark.parametrize("error", [ValueError("malformed JSON"), RuntimeError("API down"), TimeoutError()])
def test_no_verdict_fails_closed(patch_llm, error):
    patch_llm(error=error)
    out = chat_judge.judge(ROW, "answer", [])
    assert out["ok"] is False and out["failed_closed"] is True and out["error"]


def test_the_prompt_carries_the_evidence_and_the_expectations():
    p = chat_judge.prompt({**ROW, "forbid": ["7,777"]}, "the answer", ["passage one", "passage two"])
    assert "ROLE MAY ASK THIS: yes" in p and '"not covered"' in p and '"7,777"' in p and "[2] passage two" in p
    blocked = chat_judge.prompt({**ROW, "expect_blocked": True}, "x", [])
    assert "ROLE MAY ASK THIS: no" in blocked and "REFUSE" in blocked and "nothing was retrieved" in blocked


def test_contexts_are_returned_only_when_the_evaluation_asks():
    user = Principal("submitter", Role.SUBMITTER, "submitter")
    passages = [Passage(kind="policy", title="Gold plan", text="the passage text")]
    assert "contexts" not in service._result("a", "policy", user, passages=passages, cited=[1])     # what the API returns
    token = service._WITH_CONTEXTS.set(True)
    try:
        assert service._result("a", "policy", user, passages=passages, cited=[1])["contexts"] == ["the passage text"]
    finally:
        service._WITH_CONTEXTS.reset(token)
