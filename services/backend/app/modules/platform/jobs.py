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


TERMINAL_STATES: frozenset[JobState] = frozenset({JobState.SUCCEEDED, JobState.FAILED})

# Job type names are persisted in `jobs.type`, so they are renamed only with a migration.
JOB_RECORD_REALTIME_USAGE = "platform.record_realtime_usage"


def can_transition(current: JobState, target: JobState) -> bool:
    return target in VALID_TRANSITIONS[current]

