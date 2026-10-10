"""Per-step model routing. LLMs perceive and explain; deterministic code decides.

Override any step's model with ``MEDISHIELD_MODEL_<STEP>=<model id>`` (e.g. ``MEDISHIELD_MODEL_POLICY``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from medishield.config import get_settings

SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"


@dataclass(frozen=True)
class Route:
    model: str
    effort: str                      # output_config.effort (thinking cannot be disabled on these models)
    max_tokens: int
    retry_model: str | None = None   # used when the primary output fails a validation check
    image_long_edge: int = 1568      # downscale page images to bound vision tokens


ROUTES: dict[str, Route] = {
    "classifier": Route(SONNET, "low", 4000, retry_model=OPUS, image_long_edge=1100),
    "extract": Route(SONNET, "medium", 12000, retry_model=OPUS),
    "kyc_visual": Route(SONNET, "medium", 6000, retry_model=OPUS),
    # coverage itself comes from the parsed exclusion table; the model picks the benefit row and adds conditions
    "policy": Route(SONNET, "medium", 16000),   # A/B on dev: identical decisions and coverage, -33% cost per case
    # deterministic rules score fraud; the model writes the narrative and adds small, capped extra signals
    "fraud": Route(SONNET, "low", 6000),
    "justify": Route(SONNET, "low", 3000),
    # role-aware assistant
    "chat_router": Route(SONNET, "low", 2000),
    "chat_sql": Route(SONNET, "medium", 4000),
    "chat_answer": Route(SONNET, "low", 6000),
    "chat_judge": Route(OPUS, "medium", 4000),  # evaluation only: a different, stronger model grades the assistant
}


def route(step: str) -> Route:
    r = ROUTES[step]
    override = get_settings().model_overrides.get(step)
    return replace(r, model=override) if override else r
