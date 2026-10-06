"""Runtime settings, read from the environment (and ``.env``). No secrets are ever hard-coded."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[3] if len(_HERE.parents) > 3 else _HERE.parents[1]   # repo checkout, or /app in the image
DEV_JWT_SECRET = "dev-only-secret-change-me-0123456789abcdef"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _flag(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0") == "1"


@dataclass(frozen=True)
class Settings:
    # environment
    env: str = "dev"                                    # "dev" | "production"
    anthropic_api_key: str = ""
    data_root: Path = REPO_ROOT / "data" / "official"
    cache_dir: Path = Path.home() / ".cache" / "medishield"      # models, OCR, LLM responses, spend ledger
    state_dir: Path = Path.home() / ".cache" / "medishield" / "state"   # database, uploads, queue, checkpoints
    llm_cache_dir_override: str = ""
    ledger_path_override: str = ""
    # LLM
    use_fallbacks: bool = True
    llm_cache: bool = True                              # on-disk response cache (eval re-runs are free)
    llm_offline: bool = False                           # replay-only: a cache miss raises instead of calling
    budget_usd: float = 15.0                            # hard cap on cumulative recorded spend
    daily_budget_usd: float = 0.0                       # 0 = unlimited; demo deploys set this
    decision_policy: Path = Path(__file__).resolve().parent / "decision" / "decision_policy.yaml"
    model_overrides: dict[str, str] = field(default_factory=dict)
    # API
    jwt_secret: str = DEV_JWT_SECRET
    jwt_ttl_minutes: int = 480
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    demo_users: bool = True                             # seed one account per role (dev / demo deploys)
    # uploads
    max_upload_bytes: int = 10 * 1024 * 1024
    max_files_per_case: int = 10
    max_pdf_pages: int = 10
    max_image_pixels: int = 40_000_000
    # rate limits (per client, per minute)
    upload_rate_per_min: int = 10
    login_rate_per_min: int = 10
    chat_rate_per_min: int = 12
    # review workflow
    four_eyes_amount: float = 10_000.0
    sla_hours: float = 24.0
    # storage / queue
    db_backend: str = "sql"                             # "sql" (SQLite / Postgres) | "dynamodb"
    dynamo_table: str = "medishield"
    text_extract: bool = False                          # with vision_mode=auto: also try text-only extraction first (measured: -4% cost, -4 pts accuracy)
    vision_mode: str = "always"                         # "always": page images go to the model; "auto": OCR first, vision only when needed
    dynamo_endpoint_url: str = ""                       # tests / local emulators only
    aws_region: str = "us-east-1"
    storage_backend: str = "local"                      # "local" | "s3"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    queue_immediate: bool = False                       # run tasks inline (tests)
    queue_backend: str = "huey"                         # "huey" (SQLite / Redis) | "sqs" (AWS Lambda worker)
    sqs_queue_url: str = ""
    pipeline_runtime_arn: str = ""                      # AgentCore runtime that processes cases (MEDISHIELD_QUEUE=agentcore)
    assistant_runtime_arn: str = ""                     # AgentCore runtime that answers chat
    policy_ingest_function: str = ""                    # Lambda that parses uploaded policy PDFs with Docling (AWS, with S3 storage)
    api_base_path: str = ""                             # "/api" when CloudFront forwards /api/* to the Lambda
    redis_url: str = ""

    @property
    def llm_cache_dir(self) -> Path:
        return Path(self.llm_cache_dir_override) if self.llm_cache_dir_override else self.cache_dir / "llm"

    @property
    def ledger_path(self) -> Path:
        return Path(self.ledger_path_override) if self.ledger_path_override else self.cache_dir / "spend.jsonl"

    @property
    def database_url(self) -> str:
        return os.environ.get("DATABASE_URL") or f"sqlite:///{self.state_dir / 'medishield.db'}"

    @property
    def upload_dir(self) -> Path:
        return self.state_dir / "uploads"

    @property
    def policy_upload_dir(self) -> Path:
        return self.state_dir / "policies"

    @property
    def queue_path(self) -> Path:
        return self.state_dir / "queue.db"

    @property
    def checkpoint_path(self) -> Path:
        return self.state_dir / "checkpoints.db"


@lru_cache
def get_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    cache = Path(_env("MEDISHIELD_CACHE", str(Path.home() / ".cache" / "medishield")))
    overrides = {k.removeprefix("MEDISHIELD_MODEL_").lower(): v
                 for k, v in os.environ.items() if k.startswith("MEDISHIELD_MODEL_")}
    env = _env("MEDISHIELD_ENV", "dev")
    secret = _env("JWT_SECRET", DEV_JWT_SECRET)
    if env == "production" and secret == DEV_JWT_SECRET:
        raise RuntimeError("JWT_SECRET must be set when MEDISHIELD_ENV=production")
    return Settings(
        env=env,
        anthropic_api_key=_env("ANTHROPIC_API_KEY", ""),
        data_root=Path(_env("MEDISHIELD_DATA", str(REPO_ROOT / "data" / "official"))),
        cache_dir=cache,
        state_dir=Path(_env("MEDISHIELD_STATE_DIR", str(cache / "state"))),
        llm_cache_dir_override=_env("MEDISHIELD_LLM_CACHE_DIR", ""),
        ledger_path_override=_env("MEDISHIELD_LEDGER_PATH", ""),
        use_fallbacks=_flag("MEDISHIELD_FALLBACKS", True),
        llm_cache=_flag("MEDISHIELD_LLM_CACHE", True),
        llm_offline=_flag("MEDISHIELD_LLM_OFFLINE", False),
        budget_usd=float(_env("MEDISHIELD_BUDGET_USD", "15")),
        daily_budget_usd=float(_env("MEDISHIELD_DAILY_BUDGET_USD", "0")),
        model_overrides=overrides,
        jwt_secret=secret,
        jwt_ttl_minutes=int(_env("JWT_TTL_MINUTES", "480")),
        cors_origins=tuple(x for x in _env("CORS_ORIGINS", "http://localhost:3000").split(",") if x),
        demo_users=_flag("MEDISHIELD_DEMO_USERS", env != "production"),
        max_upload_bytes=int(_env("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        upload_rate_per_min=int(_env("UPLOAD_RATE_PER_MIN", "10")),
        login_rate_per_min=int(_env("LOGIN_RATE_PER_MIN", "10")),
        chat_rate_per_min=int(_env("CHAT_RATE_PER_MIN", "12")),
        four_eyes_amount=float(_env("FOUR_EYES_AMOUNT", "10000")),
        sla_hours=float(_env("SLA_HOURS", "24")),
        db_backend=_env("MEDISHIELD_DB", "sql"),
        dynamo_table=_env("DYNAMO_TABLE", "medishield"),
        vision_mode=_env("MEDISHIELD_VISION", "always").lower(),
        text_extract=_flag("MEDISHIELD_TEXT_EXTRACT", False),
        dynamo_endpoint_url=_env("DYNAMO_ENDPOINT_URL", ""),
        aws_region=_env("AWS_REGION", _env("AWS_DEFAULT_REGION", "us-east-1")),
        storage_backend=_env("STORAGE_BACKEND", "local"),
        s3_bucket=_env("S3_BUCKET", ""),
        s3_endpoint_url=_env("S3_ENDPOINT_URL", ""),
        s3_region=_env("S3_REGION", "us-east-1"),
        queue_immediate=_flag("MEDISHIELD_QUEUE_IMMEDIATE", False),
        queue_backend=_env("MEDISHIELD_QUEUE", "huey").lower(),
        sqs_queue_url=_env("SQS_QUEUE_URL", ""),
        pipeline_runtime_arn=_env("PIPELINE_RUNTIME_ARN", ""),
        assistant_runtime_arn=_env("ASSISTANT_RUNTIME_ARN", ""),
        policy_ingest_function=_env("POLICY_INGEST_FUNCTION", ""),
        api_base_path=_env("API_BASE_PATH", ""),
        redis_url=_env("REDIS_URL", ""),
    )
