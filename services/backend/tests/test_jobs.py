from app.modules.platform.jobs import JobState, can_transition


def test_job_state_machine_allows_retry_after_failure() -> None:
    assert can_transition(JobState.RUNNING, JobState.FAILED)
    assert can_transition(JobState.FAILED, JobState.QUEUED)
    assert not can_transition(JobState.SUCCEEDED, JobState.QUEUED)

