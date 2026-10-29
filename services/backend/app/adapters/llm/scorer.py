"""Structured-output scoring calls. The only place a scoring model is invoked (RULES §1).

`LLMScorer` asks for the `submit_scores` tool - forced where the model allows it, requested
in the prompt where it does not (D33) - and the caller still verifies every quote in code (D13). `StubScorer` (D31) is
deterministic and quotes real rep lines, so CI exercises the same verification path.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import anthropic

from app.adapters.llm.client import build_client, uses_direct_route
from app.adapters.llm.models import (
    CLAUDE_REFUSAL_FALLBACK_BETA,
    CLAUDE_SCORING_EFFORT,
    MODEL_PRICES_MICROUSD_PER_1M,
    NO_FORCED_TOOL_CHOICE,
)
from app.config import Settings, get_settings

log = logging.getLogger("hypersale.scoring")


class ScorerUnavailable(Exception):
    """The model could not produce a reply (API error or refusal); D33 falls back on this."""

    def __init__(self, model_id: str, reason: str) -> None:
        super().__init__(f"{model_id}: {reason}")
        self.model_id = model_id
        self.reason = reason


@dataclass(frozen=True)
class ScorerResult:
    criteria: list[dict[str, Any]]
    model_id: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    latency_ms: int
    provider: str = "agentrouter"

    @property
    def cost_microusd(self) -> int:
        prices = MODEL_PRICES_MICROUSD_PER_1M.get(self.model_id)
        if prices is None:
            return 0
        fresh_in, cached_in, out = prices
        return round(
            ((self.input_tokens - self.cache_read_tokens) * fresh_in
             + self.cache_read_tokens * cached_in + self.output_tokens * out) / 1_000_000
        )

    @property
    def rate_missing(self) -> bool:
        return self.model_id not in MODEL_PRICES_MICROUSD_PER_1M


class Scorer(Protocol):
    model_id: str

    async def score(
        self, *, system: str, user: str, tool: dict[str, Any], turns: Sequence[Any]
    ) -> ScorerResult: ...


class LLMScorer:
    """Uses the SDK's *sync* client on a worker thread. The D28 gateway admits the official
    SDK's sync client and rejects its async one as "unauthorized client" (verified
    2026-10-29), so this is the SDK as shipped, not a spoofed identity (D27)."""

    def __init__(self, settings: Settings | None = None, model_id: str | None = None) -> None:
        settings = settings or get_settings()
        self.model_id = model_id or settings.scoring_model
        self._direct = uses_direct_route(settings, self.model_id)
        self._client = build_client(settings, self.model_id)

    def request(self, *, system: str, user: str, tool: dict[str, Any]) -> dict[str, Any]:
        """The Messages request for this model (D33). Pure, so the shapes are unit-tested."""
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": 4000,
            "tools": [tool],
            "messages": [{"role": "user", "content": user}],
        }
        if self.model_id in NO_FORCED_TOOL_CHOICE:
            # Forced tool_choice is a 400 here; ask for the tool. A reply without it leaves
            # the criteria missing, which run_scoring already re-asks for.
            system = f"{system}\n\nRespond only by calling the `{tool['name']}` tool, exactly once."
            kwargs["tool_choice"] = {"type": "auto"}
            kwargs["output_config"] = {"effort": CLAUDE_SCORING_EFFORT}
        else:
            kwargs["tool_choice"] = {"type": "tool", "name": tool["name"]}
        # Stable content first so a caching provider can reuse the rubric prefix.
        kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if self._direct:
            kwargs["betas"] = [CLAUDE_REFUSAL_FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    def _call(self, kwargs: dict[str, Any]) -> Any:
        create = self._client.beta.messages.create if self._direct else self._client.messages.create
        try:
            return create(**kwargs)
        except anthropic.APIError as exc:
            raise ScorerUnavailable(self.model_id, f"{type(exc).__name__}: {exc}") from exc

    async def score(
        self, *, system: str, user: str, tool: dict[str, Any], turns: Sequence[Any]
    ) -> ScorerResult:
        started = time.perf_counter()
        response = await asyncio.to_thread(self._call, self.request(system=system, user=user, tool=tool))
        if response.stop_reason == "refusal":
            raise ScorerUnavailable(self.model_id, "refusal")
        block = next((b for b in response.content if b.type == "tool_use"), None)
        criteria = list((block.input or {}).get("criteria", [])) if block else []
        usage = response.usage
        return ScorerResult(
            criteria=criteria,
            # The direct route can be served by the API's own fallback; record who answered.
            model_id=response.model if self._direct and response.model else self.model_id,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            provider="anthropic" if self._direct else "agentrouter",
        )


class StubScorer:
    """Deterministic scorer: quotes the first words of a relevant rep turn per criterion."""

    model_id = "stub-scorer"
    KEYWORDS = {
        "opening": ("this is", "calling"),
        "discovery": ("how", "what", "?"),
        "listening": ("so ", "that makes sense", "you said"),
        "value": ("we ", "let reps", "practice"),
        "objection_handling": ("that makes sense", "fair", "understand"),
        "next_step": ("book", "tuesday", "schedule", "next"),
        "positioning": ("recording", "instead", "before"),
    }

    async def score(
        self, *, system: str, user: str, tool: dict[str, Any], turns: Sequence[Any]
    ) -> ScorerResult:
        ids = tool["input_schema"]["properties"]["criteria"]["items"]["properties"]["id"]["enum"]
        rep = [t for t in turns if t.speaker == "rep"]
        criteria = []
        for cid in ids:
            keys = self.KEYWORDS.get(cid, ())
            hit = next((t for t in rep if any(k in t.text.lower() for k in keys)), None)
            if hit is None:
                criteria.append({"id": cid, "outcome": "insufficient_evidence",
                                 "rationale": "The call did not reach this point.", "evidence": []})
                continue
            quote = " ".join(hit.text.split()[:8])
            criteria.append({
                "id": cid, "outcome": str(2 + (len(hit.text) % 3)),
                "rationale": f"Stub score based on turn {hit.idx}.",
                "evidence": [{"turn_index": hit.idx, "quote": quote}],
            })
        return ScorerResult(criteria, self.model_id, 0, 0, 0, 1)


def build_scorer(settings: Settings | None = None) -> Scorer:
    settings = settings or get_settings()
    if settings.scoring_provider == "stub":
        return StubScorer()
    return LLMScorer(settings)


def build_fallback_scorer(settings: Settings | None = None) -> Scorer | None:
    """D33: the whole-report fallback, or None when disabled, stubbed, or same as primary."""
    settings = settings or get_settings()
    fallback = settings.scoring_fallback_model
    if settings.scoring_provider == "stub" or not fallback or fallback == settings.scoring_model:
        return None
    try:
        return LLMScorer(settings, fallback)
    except Exception:  # noqa: BLE001 - a misconfigured fallback must not block the primary
        log.warning("fallback scorer unavailable", extra={"model_id": fallback}, exc_info=True)
        return None
