"""Durable job-state contract. SQL implementation follows the same state machine."""

from enum import StrEnum


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


VALID_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.QUEUED: {JobState.RUNNING},
    JobState.RUNNING: {JobState.SUCCEEDED, JobState.FAILED, JobState.QUEUED},
    JobState.SUCCEEDED: set(),
    JobState.FAILED: {JobState.QUEUED},
}


def can_transition(current: JobState, target: JobState) -> bool:
    return target in VALID_TRANSITIONS[current]

