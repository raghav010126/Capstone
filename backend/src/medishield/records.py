"""System of record: member database, claim history, statistical baselines, and processed-claim registry.

Checkpoint 2 loads the JSON exported by ``datagen/records.py``; checkpoint 3 moves this behind the database.
"""

from __future__ import annotations

import json
import statistics
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz

from medishield.config import get_settings

NAME_MATCH_MIN = 88.0


def iso_dob(s: str | None) -> str | None:
    """Accept MM/DD/YYYY (as printed) or ISO; return ISO or None."""
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d %b %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_date(s: str | None) -> date | None:
    iso = iso_dob(s)
    return date.fromisoformat(iso) if iso else None


def name_score(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return float(fuzz.token_sort_ratio(a.lower().replace(".", ""), b.lower().replace(".", "")))


@dataclass
class ProcessedClaim:
    doc_id: str
    case_id: str
    claim_number: str | None
    member_id: str | None
    service_date: str | None
    total_charge: float | None
    image_hash: str | None


@dataclass
class Records:
    members: list[dict]
    history: list[dict]
    processed: list[ProcessedClaim] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.by_policy = {m["policy_number"].upper(): m for m in self.members}
        self.history_by_member: dict[str, list[dict]] = defaultdict(list)
        for h in self.history:
            self.history_by_member[h["member_id"]].append(h)
        charges: dict[str, list[float]] = defaultdict(list)
        for h in self.history:
            for ln in h["lines"]:
                charges[ln["cpt"]].append(ln["charge"])
        self.cpt_baseline = {c: (statistics.mean(v), statistics.pstdev(v) or 1.0, len(v))
                             for c, v in charges.items() if len(v) >= 5}
        per_provider: dict[str, list[float]] = defaultdict(list)
        for h in self.history:
            per_provider[h["provider_npi"]].append(h["total_charge"])
        self.provider_baseline = {p: (statistics.mean(v), statistics.pstdev(v) or 1.0, len(v))
                                  for p, v in per_provider.items()}

    # ── member lookup ────────────────────────────────────────────────────────────────────────────────
    def find_member(self, policy: str | None = None, name: str | None = None,
                    dob: str | None = None) -> tuple[dict | None, str]:
        """Return (member, how). Policy number is the primary key; name + DOB is the fallback."""
        if policy and policy.strip().upper() in self.by_policy:
            return self.by_policy[policy.strip().upper()], "policy_number"
        dob_iso = iso_dob(dob)
        if name and dob_iso:
            cands = [m for m in self.members if m["dob"] == dob_iso]
            best = max(cands, key=lambda m: name_score(name, m["full_name"]), default=None)
            if best and name_score(name, best["full_name"]) >= NAME_MATCH_MIN:
                return best, "name_dob"
        return None, "not_found"

    # ── processed-claim registry (duplicate detection across submissions) ───────────────────────────
    def prior_claims(self) -> list[ProcessedClaim]:
        with self._lock:
            return list(self.processed)

    def register(self, claim: ProcessedClaim) -> None:
        with self._lock:
            self.processed.append(claim)

    def reset_processed(self) -> None:
        with self._lock:
            self.processed.clear()


def load_records(root: Path | None = None) -> Records:
    root = root or get_settings().data_root
    rec = root / "records"
    return Records(json.loads((rec / "members.json").read_text()),
                   json.loads((rec / "claims_history.json").read_text()))


@lru_cache
def get_records() -> Records:
    return load_records()
