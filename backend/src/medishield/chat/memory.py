"""Conversation memory: recent turns of a conversation (follow-ups) and per-user long-term memory (across sessions).

On AWS this is Amazon Bedrock AgentCore Memory (``CHAT_MEMORY_ID`` set): every turn is a short-term event, and the memory's
long-term strategies extract facts and preferences per user (namespaces ``/users/{actorId}/...``). Locally an in-process store
behaves the same way. Text is PHI-redacted before it is stored, and memory is keyed by username: one user never sees
another's.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections import defaultdict
from datetime import UTC, datetime
from functools import lru_cache

from medishield.phi import redact

log = logging.getLogger(__name__)
HISTORY_TURNS = 6


class LocalMemory:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self._notes: dict[str, list[str]] = defaultdict(list)

    def history(self, user: str, conversation: str) -> list[dict]:
        with self._lock:
            return list(self._turns[(user, conversation)][-HISTORY_TURNS:])

    def remember(self, user: str, conversation: str, question: str, answer: str) -> None:
        q, a = redact(question)[:2000], redact(answer)[:4000]
        with self._lock:
            self._turns[(user, conversation)] += [{"role": "user", "text": q}, {"role": "assistant", "text": a}]
            self._notes[user] = (self._notes[user] + [f"Asked: {q[:300]}"])[-50:]

    def recall(self, user: str, question: str, k: int = 3) -> list[str]:
        words = set(re.findall(r"[a-z0-9]{4,}", question.lower()))
        with self._lock:
            scored = sorted(self._notes[user], key=lambda n: -len(words & set(re.findall(r"[a-z0-9]{4,}", n.lower()))))
        return [n for n in scored[:k] if words & set(re.findall(r"[a-z0-9]{4,}", n.lower()))]


class AgentCoreMemory:
    def __init__(self, memory_id: str, region: str):
        import boto3

        self.memory_id = memory_id
        self.client = boto3.client("bedrock-agentcore", region_name=region)

    @staticmethod
    def _actor(user: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]", "_", user)[:100]

    def history(self, user: str, conversation: str) -> list[dict]:
        r = self.client.list_events(memoryId=self.memory_id, actorId=self._actor(user), sessionId=conversation,
                                    includePayloads=True, maxResults=HISTORY_TURNS)
        turns = []
        for ev in sorted(r.get("events", []), key=lambda e: e["eventTimestamp"]):
            for p in ev.get("payload", []):
                conv = p.get("conversational")
                if conv:
                    turns.append({"role": "user" if conv["role"] == "USER" else "assistant", "text": conv["content"]["text"]})
        return turns[-HISTORY_TURNS:]

    def remember(self, user: str, conversation: str, question: str, answer: str) -> None:
        self.client.create_event(memoryId=self.memory_id, actorId=self._actor(user), sessionId=conversation,
                                 eventTimestamp=datetime.now(UTC), payload=[
                                     {"conversational": {"role": "USER", "content": {"text": redact(question)[:2000]}}},
                                     {"conversational": {"role": "ASSISTANT", "content": {"text": redact(answer)[:4000]}}}])

    def recall(self, user: str, question: str, k: int = 3) -> list[str]:
        out = []
        for ns in ("facts", "preferences"):
            try:
                r = self.client.retrieve_memory_records(memoryId=self.memory_id, namespace=f"/users/{self._actor(user)}/{ns}",
                                                        searchCriteria={"searchQuery": question[:500], "topK": k})
                out += [m["content"]["text"] for m in r.get("memoryRecordSummaries", []) if m.get("content", {}).get("text")]
            except Exception as e:  # noqa: BLE001 - long-term records appear asynchronously; never fail an answer on them
                log.warning("memory recall (%s) skipped: %s", ns, e)
        return out[:k]


@lru_cache
def get_memory():
    mid = os.environ.get("CHAT_MEMORY_ID")
    if mid:
        from medishield.config import get_settings

        return AgentCoreMemory(mid, get_settings().aws_region)
    return LocalMemory()
