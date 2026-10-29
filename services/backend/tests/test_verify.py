"""D13 evidence checks. RULES §4 requires both negative cases: fabricated AND wrong-speaker."""
from dataclasses import dataclass

from app.modules.scoring.verify import check_quote, normalize, verify


@dataclass
class T:
    idx: int
    speaker: str
    text: str
    start_ms: int = 0
    end_ms: int = 1000


TURNS = [
    T(0, "buyer", "Priya speaking. Who is this?"),
    T(1, "rep", "Hi Priya, this is Arjun from HyperSale - I'll be quick."),
    T(2, "buyer", "We already do ride-alongs."),
    T(3, "rep", "How many reps start each quarter?"),
]


def test_verbatim_rep_quote_passes_with_timing() -> None:
    c = check_quote("opening", 1, "this is Arjun from HyperSale", TURNS)
    assert c.ok and c.speaker == "rep" and c.start_ms == 0 and c.end_ms == 1000


def test_fabricated_quote_is_rejected() -> None:
    c = check_quote("value", 1, "we cut ramp time in half", TURNS)
    assert not c.ok and c.reason == "fabricated"


def test_quote_from_the_buyer_is_rejected_as_misattributed() -> None:
    """The single most damaging failure (D13): buyer words credited to the rep."""
    c = check_quote("objection_handling", 2, "We already do ride-alongs", TURNS)
    assert not c.ok and c.reason == "misattributed" and c.speaker == "buyer"


def test_quote_real_but_cited_to_the_wrong_turn_is_rejected() -> None:
    c = check_quote("discovery", 1, "How many reps start each quarter", TURNS)
    assert not c.ok and c.reason == "fabricated"


def test_nonexistent_turn_and_too_short_quotes_are_rejected() -> None:
    assert check_quote("x", 99, "anything at all", TURNS).reason == "bad_turn"
    assert check_quote("x", 1, "Hi", TURNS).reason == "too_short"


def test_normalisation_ignores_case_punctuation_and_curly_quotes() -> None:
    assert normalize("I’ll  be QUICK!") == "i'll be quick"
    assert check_quote("opening", 1, "i’ll be quick", TURNS).ok


def test_verify_counts_each_failure_type() -> None:
    result = verify(
        [
            {"id": "opening", "evidence": [{"turn_index": 1, "quote": "Arjun from HyperSale"}]},
            {"id": "value", "evidence": [{"turn_index": 1, "quote": "invented words here"}]},
            {"id": "objection_handling", "evidence": [{"turn_index": 2, "quote": "already do ride-alongs"}]},
            {"id": "next_step", "evidence": []},
        ],
        TURNS,
    )
    assert len(result.checks) == 3
    assert result.fabricated == 1 and result.misattributed == 1
    assert {f.criterion_id for f in result.failed} == {"value", "objection_handling"}
