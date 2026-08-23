import pytest

from app.config import get_settings
from app.modules.platform.jobs import JobState, can_transition
from app.modules.platform.queue import ClaimedJob, backoff_seconds


@pytest.fixture(autouse=True)
def fixed_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOB_BACKOFF_BASE_SECONDS", "5")
    monkeypatch.setenv("JOB_BACKOFF_MAX_SECONDS", "900")
    get_settings.cache_clear()


def test_backoff_doubles_per_attempt() -> None:
    assert [backoff_seconds(n) for n in (1, 2, 3, 4)] == [5, 10, 20, 40]


def test_backoff_is_capped() -> None:
    """Without a cap the fifteenth retry lands days later, which reads as a lost job."""
    assert backoff_seconds(50) == 900


def test_backoff_handles_a_never_attempted_job() -> None:
    assert backoff_seconds(0) == 5


def test_final_attempt_is_detected_from_the_claim() -> None:
    job = ClaimedJob(
        id=None, workspace_id=None, type="t", payload={}, attempts=5, max_attempts=5
    )
    assert job.is_final_attempt
    assert not ClaimedJob(
        id=None, workspace_id=None, type="t", payload={}, attempts=4, max_attempts=5
    ).is_final_attempt


def test_state_machine_allows_retry_but_never_resurrects_success() -> None:
    assert can_transition(JobState.RUNNING, JobState.FAILED)
    assert can_transition(JobState.FAILED, JobState.QUEUED)
    assert not can_transition(JobState.SUCCEEDED, JobState.QUEUED)
