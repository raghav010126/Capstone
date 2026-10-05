"""Structured Claude calls with routing, an on-disk response cache, cost accounting and refusal fallbacks.

* Output is constrained with ``output_config.format`` (JSON schema generated from a Pydantic model) and then
  validated with Pydantic, so callers always get a typed object or an exception.
* Server-side refusal fallbacks (``fallbacks="default"``) are on by default; ``stop_reason`` is checked
  before content is read.
* Responses are cached on disk keyed by (model, effort, prompt, image hashes, schema), so eval re-runs are
  free and deterministic. ``MEDISHIELD_LLM_OFFLINE=1`` turns a cache miss into an error (CI replay).
* Every paid call is recorded in the spend ledger; the budget guard stops calls once the cap is reached.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Generic, TypeVar

import anthropic
from PIL import Image
from pydantic import BaseModel, ValidationError

from medishield.config import get_settings
from medishield.llm.cost import Usage, cost_usd, ledger
from medishield.llm.routing import Route, route
from medishield.schemas import AgentRun

log = logging.getLogger(__name__)
FALLBACK_BETA = "server-side-fallback-2026-07-01"
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """The model call failed or returned an unusable response."""


class LLMRefusal(LLMError):
    """The model (and its fallback chain) declined to answer."""


class LLMSchemaError(LLMError):
    """The response did not validate against the requested schema."""


class CacheMiss(LLMError):
    """Offline (replay) mode and the response is not cached."""


@dataclass
class LLMResult(Generic[T]):
    parsed: T
    model: str
    usage: Usage
    cost_usd: float
    latency_ms: float
    cached: bool
    step: str
    retried_with: str | None = None    # retry model, if the step escalated (kept result may be either)
    attempts: list[str] = field(default_factory=list)
    cold_cost_usd: float = 0.0         # what the call(s) cost when not served from the cache

    def run(self, agent: str) -> AgentRun:
        """Telemetry record for the agent that made this call."""
        return AgentRun(agent=agent, model=self.model, retried_with=self.retried_with,
                        input_tokens=self.usage.input_tokens, output_tokens=self.usage.output_tokens,
                        cost_usd=self.cost_usd, cold_cost_usd=self.cold_cost_usd, latency_ms=self.latency_ms,
                        llm_calls=len(self.attempts), cache_hits=int(self.cached))


# ── content helpers ──────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ImagePart:
    """A page image, downscaled to bound vision tokens. ``digest`` keys the response cache."""
    data_b64: str
    media_type: str
    digest: str


def image_part(path: str | Path, long_edge: int = 1568) -> ImagePart:
    raw = Path(path).read_bytes()
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        scale = long_edge / max(im.size)
        if scale < 1:
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()
    return ImagePart(base64.standard_b64encode(data).decode(), "image/png",
                     hashlib.sha256(raw).hexdigest()[:16] + f"@{long_edge}")


def _blocks(parts: list[str | ImagePart]) -> tuple[list[dict], list[Any]]:
    """API content blocks + a cache-key view (images replaced by their digest)."""
    blocks, key = [], []
    for p in parts:
        if isinstance(p, ImagePart):
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": p.media_type,
                                                       "data": p.data_b64}})
            key.append({"image": p.digest})
        else:
            blocks.append({"type": "text", "text": p})
            key.append(p)
    return blocks, key


# ── schema ───────────────────────────────────────────────────────────────────────────────────────────
def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic JSON schema -> structured-outputs schema: refs inlined, every property required (optional
    fields are nullable instead), ``additionalProperties: false`` everywhere, no defaults."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            node = {k: walk(v) for k, v in node.items() if k not in ("default", "title")}
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            return node
        if isinstance(node, list):
            return [walk(n) for n in node]
        return node

    return walk(schema)


# ── cache ────────────────────────────────────────────────────────────────────────────────────────────
def _cache_path(key: dict) -> Path:
    h = hashlib.sha256(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()
    return get_settings().llm_cache_dir / h[:2] / f"{h}.json"


# ── client ───────────────────────────────────────────────────────────────────────────────────────────
@lru_cache
def get_client() -> anthropic.Anthropic:
    s = get_settings()
    return anthropic.Anthropic(api_key=s.anthropic_api_key or None, max_retries=3, timeout=180.0)


def _call_api(r: Route, system: str, blocks: list[dict], schema: dict) -> tuple[str, str, Usage]:
    s = get_settings()
    kwargs: dict[str, Any] = {
        "model": r.model, "max_tokens": r.max_tokens, "system": system,
        "messages": [{"role": "user", "content": blocks}],
        "output_config": {"effort": r.effort, "format": {"type": "json_schema", "schema": schema}},
    }
    client = get_client()
    try:
        if s.use_fallbacks:
            try:
                resp = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            except anthropic.BadRequestError as e:
                if "fallback" not in str(e).lower():
                    raise
                log.warning("fallbacks rejected (%s); retrying without", e)
                resp = client.messages.create(**kwargs)
        else:
            resp = client.messages.create(**kwargs)
    except anthropic.AuthenticationError as e:
        raise LLMError("Anthropic authentication failed - check ANTHROPIC_API_KEY.") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Could not reach the Anthropic API.") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e

    u = resp.usage
    usage = Usage(u.input_tokens or 0, u.output_tokens or 0, getattr(u, "cache_read_input_tokens", 0) or 0,
                  getattr(u, "cache_creation_input_tokens", 0) or 0)
    if resp.stop_reason == "refusal":
        cost = cost_usd(resp.model, usage)
        ledger().record("refusal", resp.model, usage, cost)
        raise LLMRefusal("The model declined this request.")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if resp.stop_reason == "max_tokens":
        ledger().record("truncated", resp.model, usage, cost_usd(resp.model, usage))
        raise LLMError("Output truncated before the JSON completed (raise max_tokens).")
    return text, resp.model, usage


def structured(step: str, system: str, parts: list[str | ImagePart], out: type[T],
               model: str | None = None, tag: str = "") -> LLMResult[T]:
    """One schema-constrained call for ``step`` (see routing.ROUTES)."""
    s = get_settings()
    r = route(step)
    if model:
        r = Route(model, r.effort, r.max_tokens, None, r.image_long_edge)
    schema = strict_schema(out)
    blocks, key_view = _blocks(parts)
    key = {"v": 1, "model": r.model, "effort": r.effort, "max_tokens": r.max_tokens, "system": system,
           "content": key_view, "schema": schema}
    path = _cache_path(key)

    if s.llm_cache and path.exists():
        rec = json.loads(path.read_text())
        try:
            parsed = out.model_validate_json(rec["text"])
        except ValidationError as e:
            raise LLMSchemaError(f"{step}: cached response invalid: {e}") from e
        u = Usage(**rec["usage"])
        return LLMResult(parsed, rec["model"], u, 0.0, rec["latency_ms"], True, step, attempts=[r.model],
                         cold_cost_usd=cost_usd(rec["model"], u))
    if s.llm_offline:
        raise CacheMiss(f"{step}: no cached response (offline mode)")

    ledger().check()
    t0 = time.perf_counter()
    text, served, usage = _call_api(r, system, blocks, schema)
    latency = (time.perf_counter() - t0) * 1000
    cost = cost_usd(served, usage)
    ledger().record(step, served, usage, cost, tag)
    try:
        parsed = out.model_validate_json(text)
    except ValidationError as e:
        raise LLMSchemaError(f"{step}: response failed schema validation: {e}") from e
    if s.llm_cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"text": text, "model": served, "usage": usage.__dict__,
                                    "latency_ms": latency, "step": step, "tag": tag}))
    return LLMResult(parsed, served, usage, cost, latency, False, step, attempts=[r.model], cold_cost_usd=cost)


def structured_with_retry(step: str, system: str, parts: list[str | ImagePart], out: type[T],
                          accept: Callable[[T], bool] | None = None, tag: str = "",
                          prefer: Callable[[T, T], bool] | None = None) -> LLMResult[T]:
    """Primary model first; on an error or a failed ``accept`` check, retry on the step's retry model.

    ``prefer(retry, primary)`` picks which result to keep when both exist (default: the retry)."""
    r = route(step)
    first: LLMResult[T] | None = None
    try:
        first = structured(step, system, parts, out, tag=tag)
        if accept is None or accept(first.parsed) or not r.retry_model:
            return first
        log.info("%s %s: primary output failed check -> retry on %s", step, tag, r.retry_model)
    except (LLMSchemaError, LLMRefusal) as e:
        if not r.retry_model:
            raise
        log.warning("%s %s: %s -> retry on %s", step, tag, e, r.retry_model)
    second = structured(step, system, parts, out, model=r.retry_model, tag=tag)
    second.retried_with = r.retry_model
    second.attempts = [r.model, r.retry_model]
    if first is not None:
        second.cost_usd += first.cost_usd
        second.cold_cost_usd += first.cold_cost_usd
        second.latency_ms += first.latency_ms
        for f in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
            setattr(second.usage, f, getattr(second.usage, f) + getattr(first.usage, f))
        if prefer is not None and not prefer(second.parsed, first.parsed):
            first.retried_with, first.attempts = r.retry_model, [r.model, r.retry_model]
            first.cost_usd, first.latency_ms, first.usage = second.cost_usd, second.latency_ms, second.usage
            first.cold_cost_usd = second.cold_cost_usd
            return first
    return second
