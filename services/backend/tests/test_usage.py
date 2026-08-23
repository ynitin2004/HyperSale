import pytest

from app.modules.platform.usage import realtime_audio_cost
from tests.conftest import settings_for

PRICED = settings_for(
    realtime_audio_input_microusd_per_minute=100_000,
    realtime_audio_output_microusd_per_minute=200_000,
)
UNPRICED = settings_for()


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
