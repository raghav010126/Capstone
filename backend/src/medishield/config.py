"""Runtime settings, read from the environment (and ``.env``). No secrets are ever hard-coded."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str = ""
    data_root: Path = REPO_ROOT / "data" / "official"
    cache_dir: Path = Path.home() / ".cache" / "medishield"
    use_fallbacks: bool = True
    llm_cache: bool = True                 # on-disk response cache (eval re-runs are free + deterministic)
    llm_offline: bool = False              # replay-only: a cache miss raises instead of calling the API
    budget_usd: float = 15.0               # hard cap on cumulative spend recorded in the ledger
    decision_policy: Path = Path(__file__).resolve().parent / "decision" / "decision_policy.yaml"
    model_overrides: dict[str, str] = field(default_factory=dict)

    @property
    def llm_cache_dir(self) -> Path:
        return self.cache_dir / "llm"

    @property
    def ledger_path(self) -> Path:
        return self.cache_dir / "spend.jsonl"


@lru_cache
def get_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    overrides = {k.removeprefix("MEDISHIELD_MODEL_").lower(): v
                 for k, v in os.environ.items() if k.startswith("MEDISHIELD_MODEL_")}
    return Settings(
        anthropic_api_key=_env("ANTHROPIC_API_KEY", ""),
        data_root=Path(_env("MEDISHIELD_DATA", str(REPO_ROOT / "data" / "official"))),
        cache_dir=Path(_env("MEDISHIELD_CACHE", str(Path.home() / ".cache" / "medishield"))),
        use_fallbacks=_env("MEDISHIELD_FALLBACKS", "1") == "1",
        llm_cache=_env("MEDISHIELD_LLM_CACHE", "1") == "1",
        llm_offline=_env("MEDISHIELD_LLM_OFFLINE", "0") == "1",
        budget_usd=float(_env("MEDISHIELD_BUDGET_USD", "15")),
        model_overrides=overrides,
    )
