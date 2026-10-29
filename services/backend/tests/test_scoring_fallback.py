"""D33: dual-model scoring. Request shape per model, error classification, whole-report fallback."""
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.adapters.llm.models import SCORING_MODEL, SCORING_MODEL_CLAUDE
from app.adapters.llm.scorer import (
    LLMScorer,
    ScorerResult,
    ScorerUnavailable,
    StubScorer,
    build_fallback_scorer,
)
from app.config import Settings
from app.modules.scoring import prompt as scoring_prompt
from app.modules.scoring.service import score_with_fallback
from tests.test_scoring_run import CRITERIA, TURNS

GATEWAY = {"anthropic_auth_token": "t", "anthropic_base_url": "https://gateway.example"}
TOOL = scoring_prompt.build_tool(["opening", "next_step"])


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**GATEWAY, **overrides})


def test_gpt_keeps_the_forced_tool_call_through_the_gateway() -> None:
    scorer = LLMScorer(_settings(), SCORING_MODEL)
    req = scorer.request(system="s", user="u", tool=TOOL)
    assert req["tool_choice"] == {"type": "tool", "name": TOOL["name"]}
    assert "output_config" not in req and "betas" not in req
    assert str(scorer._client.base_url).startswith("https://gateway.example")


def test_claude_is_asked_for_the_tool_instead_of_forced() -> None:
    req = LLMScorer(_settings(), SCORING_MODEL_CLAUDE).request(system="s", user="u", tool=TOOL)
    assert req["tool_choice"] == {"type": "auto"}  # forced tool_choice is a 400 on Opus 5.5
    assert req["output_config"] == {"effort": "medium"}
    assert TOOL["name"] in req["system"][0]["text"]
    assert not {"temperature", "top_p", "top_k", "thinking"} & req.keys()
    assert "fallbacks" not in req  # the gateway route gets no Anthropic-only beta


def test_claude_goes_direct_only_when_a_claude_key_is_set() -> None:
    scorer = LLMScorer(_settings(claude_api_key="direct"), SCORING_MODEL_CLAUDE)
    assert "anthropic.com" in str(scorer._client.base_url)
    req = scorer.request(system="s", user="u", tool=TOOL)
    assert req["fallbacks"] == "default" and req["betas"]
    # A non-Claude model never uses the Claude key.
    gpt = LLMScorer(_settings(claude_api_key="direct"), SCORING_MODEL)
    assert str(gpt._client.base_url).startswith("https://gateway.example")


def test_api_errors_and_refusals_become_scorer_unavailable() -> None:
    scorer = LLMScorer(_settings(), SCORING_MODEL_CLAUDE)
    request = httpx.Request("POST", "https://gateway.example/v1/messages")
    response = httpx.Response(503, request=request, json={"error": {"message": "no channel"}})

    def boom(**_kwargs):
        raise anthropic.InternalServerError("no channel", response=response, body=None)

    scorer._client = SimpleNamespace(messages=SimpleNamespace(create=boom))
    with pytest.raises(ScorerUnavailable, match="no channel"):
        scorer._call({})

    refused = SimpleNamespace(stop_reason="refusal", content=[], usage=None, model=SCORING_MODEL_CLAUDE)
    scorer._client = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: refused))
    import asyncio
    with pytest.raises(ScorerUnavailable, match="refusal"):
        asyncio.run(scorer.score(system="s", user="u", tool=TOOL, turns=TURNS))


def test_fallback_scorer_rules() -> None:
    assert build_fallback_scorer(_settings(scoring_provider="stub")) is None
    assert build_fallback_scorer(_settings(scoring_fallback_model="")) is None
    assert build_fallback_scorer(_settings(scoring_fallback_model=SCORING_MODEL)) is None
    assert build_fallback_scorer(_settings()).model_id == SCORING_MODEL_CLAUDE


class DownScorer:
    """Answers the first call, fails the second: a mid-report outage."""

    model_id = "primary-down"

    def __init__(self) -> None:
        self.calls = 0

    async def score(self, *, system, user, tool, turns):
        self.calls += 1
        if self.calls > 1:
            raise ScorerUnavailable(self.model_id, "InternalServerError: no channel")
        ids = tool["input_schema"]["properties"]["criteria"]["items"]["properties"]["id"]["enum"]
        return ScorerResult([{"id": i, "outcome": "5", "rationale": "r", "evidence": []} for i in ids],
                            self.model_id, 10, 10, 0, 1)


async def test_fallback_rescores_the_whole_report_on_one_model() -> None:
    primary, fallback = DownScorer(), StubScorer()
    raw, failed, calls, fallback_from = await score_with_fallback(
        primary, fallback, criteria=CRITERIA * 2, turns=TURNS, buyer_name="Priya", scenario_title="t")
    assert fallback_from == {"model_id": "primary-down", "reason": "InternalServerError: no channel"}
    # Nothing from the primary survives: every call, hence the provenance, is the fallback's.
    assert calls and {c.model_id for c in calls} == {"stub-scorer"}
    assert all(c["outcome"] != "5" for c in raw)


async def test_without_a_fallback_the_outage_propagates_to_the_job_retry() -> None:
    primary = DownScorer()
    primary.calls = 1
    with pytest.raises(ScorerUnavailable):
        await score_with_fallback(primary, None, criteria=CRITERIA, turns=TURNS,
                                  buyer_name="Priya", scenario_title="t")
