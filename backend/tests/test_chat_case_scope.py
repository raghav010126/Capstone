"""Ask about this case: a question from a case page is about that case, with no extra model call and the same boundaries
(all model calls stubbed)."""

from __future__ import annotations

import time
import uuid

import pytest
from conftest import fake_state, png_bytes
from medishield.api.security import Principal, Role
from medishield.chat import router, scope, service
from medishield.chat import sources as src
from medishield.chat.router import RouteOut
from medishield.llm import LLMError

SUB = Principal("submitter", Role.SUBMITTER, "S")
SUB2 = Principal("submitter2", Role.SUBMITTER, "S2")
REV = Principal("reviewer", Role.REVIEWER, "R")
REAL_CLASSIFY = router.classify
POLICY = {"coverage_status": "NOT_COVERED", "plan": "gold", "policy_clause": "Section 4.1 cosmetic exclusions",
          "per_code": [{"code": "17000", "status": "NOT_COVERED"}, {"code": "11400", "status": "COVERED"}]}


def make_case(user: Principal, policy: dict | None = None) -> str:
    from medishield.db.repo import repo_scope
    from medishield.services import cases

    with repo_scope() as db:
        case, _w, _c = cases.create_case(db, user, [("a.png", png_bytes(text_seed=hash(user.username) % 50))], None)
        cid, docs = case.id, [d.doc_id for d in case.documents]
    state = fake_state(docs, "REJECT", 900.0, 0.1)
    if policy:
        state["specialists"][docs[0]] = {"policy": policy}
    with repo_scope() as db:
        cases.persist_result(db, db.get_case(cid), state, False, 10.0)
    return cid


def route(**kw) -> RouteOut:
    base = {"route": "help", "sources": [], "case_ids": [], "cpt_codes": [], "plans": [], "sql_tables": [], "standalone_question": "q"}
    return RouteOut(**{**base, **kw})


class Res:
    def __init__(self, parsed):
        self.parsed = parsed


@pytest.fixture
def chat(env, monkeypatch):
    """Stub the router (per test) and the answer model; record what each of them received."""
    seen: dict = {"route": None, "router_history": [], "chat_answer": []}

    def answer_model(step, system, parts, out, **k):
        assert step == "chat_answer", step
        seen["chat_answer"].append(parts[0])
        return Res(out(answer="stub answer [1]", cited=[1]))

    def classify(q, h=None, tag=""):
        seen["router_history"].append(list(h or []))
        return seen["route"].model_copy(deep=True), "llm"

    monkeypatch.setattr(service, "structured", answer_model)
    monkeypatch.setattr(router, "classify", classify)
    return seen


def ask(user: Principal, question: str, case_id: str | None = None, conversation: str | None = None) -> dict:
    payload = {"user": {"username": user.username, "role": user.role.value}, "question": question,
               "conversation_id": conversation or f"conv-{uuid.uuid4().hex}"}
    if case_id:
        payload["case_id"] = case_id
    return service.answer(payload)


def fake_policy(calls: list):
    def policy_passages(question, plans, codes, k=3):
        calls.append((plans, codes))
        return [src.Passage("exclusion", "Gold plan, table 4.1 - CPT 17000", "CPT 17000: excluded (cosmetic)")]
    return policy_passages


# ── the page's case is the subject ──────────────────────────────────────────────────────────────────
def test_a_scoped_question_routes_to_the_case_and_includes_its_passage(chat):
    cid = make_case(SUB)
    chat["route"] = route(route="case", sources=["all_cases"])       # the router dropped the id and guessed "other people's cases"
    out = ask(SUB, "Why was this case decided this way?", cid)
    assert out["route"] == "case" and not out["blocked"]
    assert out["sources"][0]["url"] == f"/cases/view?id={cid}" and out["sources"][0]["cited"]
    assert any(t["role"] == "page" and cid in t["text"] for t in chat["router_history"][-1])     # a hint, not another call
    prompt = chat["chat_answer"][-1]
    assert len(chat["chat_answer"]) == 1 and f"Case {cid}" in prompt and f"Asked from the page of case {cid}" in prompt


def test_a_follow_up_why_goes_to_the_case_and_keeps_the_conversation(chat, monkeypatch):
    cid, conv = make_case(SUB), f"conv-{uuid.uuid4().hex}"
    chat["route"] = route(route="case", case_ids=[cid])
    ask(SUB, "Why was this case decided this way?", cid, conv)
    from medishield.chat.memory import get_memory

    for _ in range(100):                                              # memory is written in the background
        if get_memory().history(SUB.username, conv):
            break
        time.sleep(0.01)
    prompts = []

    def router_model(step, system, parts, out, **k):                  # the router model is unavailable: keyword routing
        prompts.append(parts[0])
        raise LLMError("router unavailable")

    monkeypatch.setattr(router, "classify", REAL_CLASSIFY)
    monkeypatch.setattr(router, "structured", router_model)
    out = ask(SUB, "why?", cid, conv)
    assert out["route"] == "case" and out["router"] == "keyword" and out["sources"][0]["url"] == f"/cases/view?id={cid}"
    assert "Why was this case decided this way?" in prompts[0] and cid in prompts[0]      # earlier turn and the page's case
    assert "Earlier in this conversation" in chat["chat_answer"][-1]


@pytest.mark.parametrize("r,question,expected", [
    (route(route="off_topic"), "What would change the decision?", ("case", ["CASE-0000000A"])),
    (route(route="help"), "Which policy clause applies?", ("case", ["CASE-0000000A"])),
    (route(route="off_topic"), "Write me a poem about cats", ("off_topic", [])),
    (route(route="help"), "hello", ("help", [])),
    (route(route="case", sources=["all_cases"], case_ids=["CASE-0000000B"]), "Compare with CASE-0000000B", ("case", ["CASE-0000000A", "CASE-0000000B"])),
    (route(route="audit", sources=["audit"]), "Who overrode this case?", ("audit", ["CASE-0000000A"])),
    (route(route="analytics", sources=["all_cases"], sql_tables=["cases"]), "How many cases like this?", ("analytics", [])),
])
def test_scope_rules(r, question, expected):
    out = scope.apply(r, "CASE-0000000A", question)
    assert (out.route, out.case_ids) == expected
    assert ("all_cases" in out.sources) == (out.route == "analytics")       # ownership is the case tool's call


# ── access still holds ──────────────────────────────────────────────────────────────────────────────
def test_a_submitter_scoping_to_someone_elses_case_gets_not_visible_and_nothing_leaks(chat, monkeypatch):
    theirs = make_case(SUB2, POLICY)
    calls: list = []
    monkeypatch.setattr(src, "policy_passages", fake_policy(calls))
    chat["route"] = route(route="case", sources=["own_cases"])
    out = ask(SUB, "Why was this case decided this way?", theirs)
    assert not out["sources"] and f"No case {theirs} is visible to you" in out["answer"] and not chat["chat_answer"]
    missing = ask(SUB, "Why was this case decided this way?", "CASE-00000000")
    assert missing["answer"].replace("CASE-00000000", theirs) == out["answer"]            # same reply as for no such case

    chat["route"] = route(route="policy", sources=["policies"])
    out = ask(SUB, "Which policy clause applies?", theirs)
    assert calls[-1] == ([], [])                                      # the hidden case's codes and plan are not used either
    assert [s["kind"] for s in out["sources"]] == ["exclusion"]
    prompt = chat["chat_answer"][-1]
    assert f"Case {theirs}" not in prompt and "Asked from the page" not in prompt and "submitter2" not in prompt
    assert f"No case {theirs} is visible to you" in prompt


def test_a_reviewer_may_ask_about_any_case_and_policy_questions_use_its_codes_and_plan(chat, monkeypatch):
    theirs = make_case(SUB2, POLICY)
    calls: list = []
    monkeypatch.setattr(src, "policy_passages", fake_policy(calls))
    chat["route"] = route(route="case", sources=["all_cases"])
    out = ask(REV, "What would change the decision?", theirs)
    assert out["route"] == "case" and out["sources"][0]["url"] == f"/cases/view?id={theirs}"
    assert "17000 NOT_COVERED" in chat["chat_answer"][-1]

    chat["route"] = route(route="policy", sources=["policies"])
    out = ask(REV, "Which policy clause applies to this case?", theirs)
    assert calls[-1] == (["gold"], ["17000", "11400"])
    assert [s["kind"] for s in out["sources"]] == ["case", "exclusion"]
    chat["route"] = route(route="policy", sources=["policies"], plans=["silver"], cpt_codes=["99213"])
    ask(REV, "Is CPT 99213 covered on Silver?", theirs)
    assert calls[-1] == (["silver"], ["99213"])                       # what the question names wins


def test_without_a_case_id_nothing_changes(chat):
    make_case(SUB)
    chat["route"] = route(route="case", sources=["own_cases"])
    out = ask(SUB, "Why was my latest claim decided that way?")
    assert [s["title"] for s in out["sources"]] == ["Your most recent cases"]
    assert chat["router_history"][-1] == [] and "Asked from the page" not in chat["chat_answer"][-1]
    chat["route"] = route(route="off_topic")
    assert ask(SUB, "why?")["route"] == "off_topic"


# ── the API ──────────────────────────────────────────────────────────────────────────────────────────
def test_chat_endpoint_passes_the_case_id_only_when_given(client, auth, monkeypatch):
    from medishield.api.routes import chat as chat_route

    payloads = []

    def run(p):
        payloads.append(p)
        return {"answer": "a", "route": "case", "blocked": False, "role": p["user"]["role"], "conversation_id": p["conversation_id"]}

    monkeypatch.setattr(chat_route, "_run", run)
    h = auth("submitter")
    assert client.post("/chat", json={"question": "why?", "case_id": "CASE-1a2b3c4d"}, headers=h).status_code == 200
    assert payloads[-1]["case_id"] == "CASE-1A2B3C4D"
    assert client.post("/chat", json={"question": "why?"}, headers=h).status_code == 200
    assert "case_id" not in payloads[-1]
    assert client.post("/chat", json={"question": "why?", "case_id": "../../etc"}, headers=h).status_code == 422
