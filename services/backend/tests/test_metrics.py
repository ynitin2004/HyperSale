from dataclasses import dataclass

from app.modules.scoring.metrics import METRICS_VERSION, compute_metrics


@dataclass
class T:
    speaker: str
    text: str
    start_ms: int
    end_ms: int


def test_metrics_on_a_short_call() -> None:
    turns = [
        T("buyer", "Hello, who is this?", 0, 1000),
        T("rep", "Hi, um, this is Arjun. How do your reps practice today? What tools do you use?", 1200, 6000),
        T("buyer", "Ride-alongs, mostly.", 6200, 7000),
        T("rep", "Could we book a demo next Tuesday at 10am?", 7200, 9000),
    ]
    m = compute_metrics(turns)
    assert m["metrics_version"] == METRICS_VERSION
    assert m["rep_turns"] == 2 and m["buyer_turns"] == 2
    assert m["questions"] == 3 and m["open_questions"] == 2
    assert m["filler_words"] == 1
    assert m["next_step_with_date"] is True
    assert m["next_step_quote"].startswith("Could we book")
    assert m["duration_ms"] == 9000
    assert 0.5 < m["talk_ratio_rep"] < 1


def test_no_next_step_without_a_date() -> None:
    m = compute_metrics([T("rep", "Can we schedule a call sometime?", 0, 1000)])
    assert m["next_step_with_date"] is False and m["next_step_quote"] is None


def test_empty_transcript_is_safe() -> None:
    m = compute_metrics([])
    assert m["turns"] == 0 and m["talk_ratio_rep"] is None and m["duration_ms"] == 0
