"""Structured-output scoring calls. The only place a scoring model is invoked (RULES §1).

`LLMScorer` forces the `submit_scores` tool, which makes the reply schema-shaped by
construction; the caller still verifies every quote in code (D13). `StubScorer` (D31) is
deterministic and quotes real rep lines, so CI exercises the same verification path.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.adapters.llm.client import build_client
from app.adapters.llm.models import MODEL_PRICES_MICROUSD_PER_1M, SCORING_MODEL
from app.config import Settings, get_settings


@dataclass(frozen=True)
class ScorerResult:
    criteria: list[dict[str, Any]]
    model_id: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    latency_ms: int

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

    def __init__(self, settings: Settings | None = None, model_id: str = SCORING_MODEL) -> None:
        self._client = build_client(settings)
        self.model_id = model_id

    async def score(
        self, *, system: str, user: str, tool: dict[str, Any], turns: Sequence[Any]
    ) -> ScorerResult:
        started = time.perf_counter()
        response = await asyncio.to_thread(
            self._client.messages.create,
            model=self.model_id,
            max_tokens=4000,
            # Stable content first so a caching provider can reuse the rubric prefix.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": user}],
        )
        block = next((b for b in response.content if b.type == "tool_use"), None)
        criteria = list((block.input or {}).get("criteria", [])) if block else []
        usage = response.usage
        return ScorerResult(
            criteria=criteria,
            model_id=self.model_id,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
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
