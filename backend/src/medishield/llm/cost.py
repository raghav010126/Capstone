"""Token pricing, a persistent spend ledger, and a hard budget guard."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from medishield.config import get_settings

# USD per million tokens: (input, output, cache read). Cache writes bill at 1.25x input.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}
_FALLBACK_PRICE = (5.00, 25.00, 0.50)     # unknown (e.g. refusal-fallback) model: price conservatively


class BudgetExceeded(RuntimeError):
    """Cumulative recorded spend reached MEDISHIELD_BUDGET_USD; no further paid calls are made."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


def cost_usd(model: str, u: Usage) -> float:
    pin, pout, pread = PRICES.get(model, _FALLBACK_PRICE)
    return (u.input_tokens * pin + u.output_tokens * pout + u.cache_read_tokens * pread
            + u.cache_write_tokens * pin * 1.25) / 1e6


class Ledger:
    """Append-only JSONL of every paid call. The running total survives restarts, so the budget is global."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path = get_settings().ledger_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.total = 0.0
        if self._path.exists():
            for line in self._path.read_text().splitlines():
                if line.strip():
                    self.total += json.loads(line).get("cost_usd", 0.0)

    def check(self) -> None:
        budget = get_settings().budget_usd
        if self.total >= budget:
            raise BudgetExceeded(f"recorded spend ${self.total:.2f} >= budget ${budget:.2f}")

    def spent_today(self) -> float:
        """Spend recorded since 00:00 UTC (the demo deploy's daily cap)."""
        midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        total = 0.0
        if self._path.exists():
            for line in self._path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    if rec["ts"] >= midnight:
                        total += rec.get("cost_usd", 0.0)
        return total

    def check_daily(self) -> None:
        cap = get_settings().daily_budget_usd
        if cap > 0 and self.spent_today() >= cap:
            raise BudgetExceeded(f"daily budget ${cap:.2f} reached")

    def record(self, step: str, model: str, usage: Usage, cost: float, tag: str = "") -> None:
        with self._lock:
            self.total += cost
            with self._path.open("a") as f:
                f.write(json.dumps({"ts": time.time(), "step": step, "model": model, "cost_usd": round(cost, 6),
                                    "tag": tag, **asdict(usage)}) + "\n")


class DynamoLedger(Ledger):
    """The same ledger kept in DynamoDB (atomic counters), for Lambda where there is no durable local disk and many
    invocations run at once. One item holds the running total; one item per UTC day holds that day's spend."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _table(self):
        from medishield.db.dynamo import get_dynamo_repo

        return get_dynamo_repo().table

    @staticmethod
    def _day_key(ts: float | None = None) -> str:
        return "LEDGER#" + datetime.fromtimestamp(ts or time.time(), UTC).strftime("%Y-%m-%d")

    def _read(self, pk: str) -> float:
        item = self._table().get_item(Key={"pk": pk, "sk": "META"}, ConsistentRead=True).get("Item")
        return float(item["usd"]) if item else 0.0

    @property
    def total(self) -> float:                     # type: ignore[override]
        return self._read("LEDGER#total")

    def spent_today(self) -> float:
        return self._read(self._day_key())

    def record(self, step: str, model: str, usage: Usage, cost: float, tag: str = "") -> None:
        from decimal import Decimal

        amount = Decimal(str(round(cost, 6)))
        t = self._table()
        t.update_item(Key={"pk": "LEDGER#total", "sk": "META"}, UpdateExpression="ADD usd :c, calls :one",
                      ExpressionAttributeValues={":c": amount, ":one": 1})
        t.update_item(Key={"pk": self._day_key(), "sk": "META"}, UpdateExpression="ADD usd :c SET #t = :ttl",
                      ExpressionAttributeNames={"#t": "ttl"}, ExpressionAttributeValues={":c": amount, ":ttl": int(time.time()) + 30 * 86400})


_ledger: Ledger | None = None
_ledger_lock = threading.Lock()


def ledger() -> Ledger:
    global _ledger
    with _ledger_lock:
        if _ledger is None:
            _ledger = DynamoLedger() if get_settings().db_backend == "dynamodb" else Ledger()
        return _ledger
