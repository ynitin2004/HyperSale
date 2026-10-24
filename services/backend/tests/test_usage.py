import pytest

from app.modules.platform.usage import RealtimeTokens, realtime_audio_cost, realtime_token_cost
from tests.conftest import settings_for

PRICED = settings_for(
    realtime_audio_input_microusd_per_minute=100_000,
    realtime_audio_output_microusd_per_minute=200_000,
)
UNPRICED = settings_for()
# gpt-realtime list prices: $4 / $0.40 / $32 / $0.40 / $16 / $64 per 1M tokens.
TOKEN_PRICED = settings_for(
    realtime_text_input_microusd_per_1m=4_000_000,
    realtime_text_cached_input_microusd_per_1m=400_000,
    realtime_audio_input_microusd_per_1m=32_000_000,
    realtime_audio_cached_input_microusd_per_1m=400_000,
    realtime_text_output_microusd_per_1m=16_000_000,
    realtime_audio_output_microusd_per_1m=64_000_000,
)


def test_token_cost_prices_each_bucket() -> None:
    # The measured 2026-10-24 Chromium spike session, rounded per bucket.
    tokens = RealtimeTokens(
        text_in=676, text_in_cached=1280, audio_in=268, audio_in_cached=0, text_out=21, audio_out=149
    )
    cost = realtime_token_cost(tokens, settings=TOKEN_PRICED)
    assert cost.cost_microusd == 2_704 + 512 + 8_576 + 0 + 336 + 9_536
    assert cost.rate_missing is False
    assert tokens.input_total == 2_224 and tokens.output_total == 170


def test_token_cost_flags_a_used_bucket_without_a_rate() -> None:
    cost = realtime_token_cost(RealtimeTokens(audio_in=10), settings=UNPRICED)
    assert cost.cost_microusd == 0 and cost.rate_missing is True
    # An unused bucket's missing rate is not a problem.
    assert realtime_token_cost(RealtimeTokens(), settings=UNPRICED).rate_missing is False


def test_token_cost_rejects_negative_counts() -> None:
    with pytest.raises(ValueError):
        realtime_token_cost(RealtimeTokens(text_in=-1), settings=TOKEN_PRICED)


def test_cost_is_summed_per_direction() -> None:
    cost = realtime_audio_cost(input_seconds=180, output_seconds=60, settings=PRICED)
    assert cost.cost_microusd == 300_000 + 200_000
    assert cost.rate_missing is False


def test_partial_minutes_round_to_whole_micro_usd() -> None:
    cost = realtime_audio_cost(input_seconds=1, output_seconds=0, settings=PRICED)
    assert cost.cost_microusd == round(100_000 / 60)


def test_unmeasured_rate_is_flagged_rather_than_priced_at_zero() -> None:
    """A zero cost must be distinguishable from a genuinely free call."""
    cost = realtime_audio_cost(input_seconds=180, output_seconds=120, settings=UNPRICED)
    assert cost.cost_microusd == 0
    assert cost.rate_missing is True


def test_no_audio_is_not_a_missing_rate() -> None:
    cost = realtime_audio_cost(input_seconds=0, output_seconds=0, settings=UNPRICED)
    assert cost.rate_missing is False


def test_negative_duration_is_rejected() -> None:
    with pytest.raises(ValueError):
        realtime_audio_cost(input_seconds=-1, output_seconds=0, settings=PRICED)
