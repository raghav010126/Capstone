"""Task queue (Huey). SQLite-backed by default, Redis when ``REDIS_URL`` is set, inline when
``MEDISHIELD_QUEUE_IMMEDIATE=1`` (tests).

A single worker thread drains the queue. It can live in the API process (one-container deploys) or run on its
own (``python -m medishield.worker.queue``) - the database is the only shared state.
"""

from __future__ import annotations

import logging
import threading
import time
from functools import lru_cache

from huey import Huey, RedisHuey, SqliteHuey

from medishield.config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def get_huey() -> Huey:
    s = get_settings()
    if s.redis_url:
        return RedisHuey("medishield", url=s.redis_url, immediate=s.queue_immediate)
    s.state_dir.mkdir(parents=True, exist_ok=True)
    return SqliteHuey("medishield", filename=str(s.queue_path), immediate=s.queue_immediate)


@lru_cache
def tasks() -> dict:
    """Task wrappers, registered exactly once per queue instance (Huey rejects duplicate registration)."""
    from medishield.services.cases import process_case
    from medishield.services.policies import ingest_policy

    h = get_huey()
    return {"process_case": h.task(retries=0, name="process_case")(process_case),
            "ingest_policy": h.task(retries=0, name="ingest_policy")(ingest_policy)}


def enqueue_case(case_id: str) -> None:
    tasks()["process_case"](case_id)


def enqueue_policy(policy_id: int) -> None:
    tasks()["ingest_policy"](policy_id)


class Worker(threading.Thread):
    def __init__(self, poll: float = 0.5):
        super().__init__(daemon=True, name="medishield-worker")
        self.poll, self._stop_evt = poll, threading.Event()

    def run(self) -> None:
        tasks()
        h = get_huey()
        while not self._stop_evt.is_set():
            try:
                task = h.dequeue()
            except Exception:
                log.exception("queue read failed")
                time.sleep(2)
                continue
            if task is None:
                time.sleep(self.poll)
                continue
            try:
                h.execute(task)
            except Exception:
                log.exception("task %s failed", getattr(task, "name", "?"))

    def stop(self) -> None:
        self._stop_evt.set()


def start_worker() -> Worker:
    w = Worker()
    w.start()
    return w


if __name__ == "__main__":                                      # pragma: no cover - standalone worker process
    logging.basicConfig(level=logging.INFO)
    from medishield.services.cases import rebuild_registry

    log.info("rebuilt claim registry: %d claims", rebuild_registry())
    w = Worker()
    w.run()
