from app.modules.platform.jobs import JobState


def test_job_state_is_string_for_persistence() -> None:
    assert JobState.QUEUED == "queued"

