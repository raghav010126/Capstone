"""Amazon Bedrock AgentCore Runtime entry point (HTTP protocol: POST /invocations, GET /ping on port 8080).

One container image serves two runtimes; ``AGENT_ROLE`` selects what this one does:

``pipeline``   ``{"task": "process_case", "case_id": ...}`` / ``{"task": "ingest_policy", "policy_id": ...}``. The request returns
               at once and the work continues as a registered async task, so ``/ping`` reports HealthyBusy and AgentCore keeps
               the session alive until the case is decided (a case takes ~30 s; sessions may live for hours).
``assistant``  ``{"task": "chat", ...}``: the role-aware assistant (added with the chat module).

The API Lambda is the only caller (IAM-authorised ``InvokeAgentRuntime``); it passes the authenticated principal in the payload.
"""

from __future__ import annotations

import logging
import os
import threading

from bedrock_agentcore import BedrockAgentCoreApp

from medishield.aws_handlers import _init

log = logging.getLogger(__name__)
app = BedrockAgentCoreApp()
ROLE = os.environ.get("AGENT_ROLE", "pipeline")


def _preload() -> None:
    """Load the heavy parts while the microVM starts, instead of halfway through the first case or question."""
    try:
        _init()
        from medishield.rag.retrieve import get_store

        if ROLE == "pipeline":
            import medishield.pipeline  # noqa: F401
            from medishield.ocr.engine import _engine

            _engine("default")
        get_store()
    except Exception:
        log.exception("preload failed (work will load on first use)")


if os.environ.get("AGENTCORE_PRELOAD", "1") == "1" and os.environ.get("DOCKER_CONTAINER"):
    threading.Thread(target=_preload, daemon=True, name="preload").start()


def _run_case(case_id: str, task_id: int) -> None:
    from medishield.records import get_records
    from medishield.services import cases

    try:
        records = get_records()
        records.reset_processed()
        cases.rebuild_registry()                    # duplicate detection needs every earlier decided claim
        cases.process_case(case_id)                 # failures are recorded on the case itself
    except Exception:
        log.exception("case %s crashed outside the pipeline", case_id)
    finally:
        app.complete_async_task(task_id)


def _run_policy(policy_id: int, task_id: int) -> None:
    from medishield.services import policies

    try:
        policies.ingest_policy(policy_id)
    finally:
        app.complete_async_task(task_id)


def _background(target, arg, name: str) -> None:
    task_id = app.add_async_task(name, {"arg": str(arg)})
    threading.Thread(target=target, args=(arg, task_id), daemon=True, name=f"{name}-{arg}").start()


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    _init()
    task = payload.get("task")
    if ROLE == "pipeline":
        if task == "process_case":
            _background(_run_case, str(payload["case_id"]), "process_case")
            return {"accepted": True, "task": task, "case_id": payload["case_id"]}
        if task == "ingest_policy":
            _background(_run_policy, int(payload["policy_id"]), "ingest_policy")
            return {"accepted": True, "task": task, "policy_id": payload["policy_id"]}
    if ROLE == "assistant" and task in ("chat", "warm", "forget"):
        from medishield.chat import service  # the role-aware assistant

        return {"chat": service.answer, "warm": lambda p: service.warm(), "forget": service.forget}[task](payload)
    return {"error": f"unsupported task {task!r} for the {ROLE} runtime"}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(port=8080, host="0.0.0.0")
