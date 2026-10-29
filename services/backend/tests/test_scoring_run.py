"""Retry-then-degrade (D13) without a database: the model is a scripted fake."""
from dataclasses import dataclass

from app.adapters.llm.scorer import ScorerResult
from app.modules.catalog.service import Criterion
from app.modules.scoring.service import pick_drill_criteria, run_scoring


@dataclass
class T:
    idx: int
    speaker: str
    text: str
    start_ms: int = 0
    end_ms: int = 500


TURNS = [
    T(0, "buyer", "Who's calling?"),
    T(1, "rep", "This is Arjun from HyperSale, calling about rep coaching."),
    T(2, "buyer", "We already have Gong."),
    T(3, "rep", "Could we book Tuesday at ten?"),
]
CRITERIA = [Criterion("opening", "Opening", "d"), Criterion("next_step", "Next step", "d")]


class ScriptedScorer:
    model_id = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def score(self, *, system, user, tool, turns):
        ids = tool["input_schema"]["properties"]["criteria"]["items"]["properties"]["id"]["enum"]
        self.calls.append({"ids": ids, "user": user})
        return ScorerResult(self.replies.pop(0), "fake", 100, 50, 0, 5)


async def test_fabricated_quote_is_retried_with_feedback_and_fixed() -> None:
    scorer = ScriptedScorer([
        [{"id": "opening", "outcome": "3", "rationale": "r",
          "evidence": [{"turn_index": 1, "quote": "we transform sales teams"}]},
         {"id": "next_step", "outcome": "4", "rationale": "r",
          "evidence": [{"turn_index": 3, "quote": "book Tuesday at ten"}]}],
        [{"id": "opening", "outcome": "3", "rationale": "r",
          "evidence": [{"turn_index": 1, "quote": "Arjun from HyperSale"}]}],
    ])
    raw, failed, calls = await run_scoring(scorer, criteria=CRITERIA, turns=TURNS,
                                           buyer_name="Priya", scenario_title="t")
    assert failed == [] and len(calls) == 2
    # Only the failing criterion is re-asked, and the feedback names the bad quote.
    assert scorer.calls[1]["ids"] == ["opening"]
    assert "we transform sales teams" in scorer.calls[1]["user"]
    assert {c["id"] for c in raw} == {"opening", "next_step"}


async def test_persistent_misattribution_stops_after_the_retry_cap() -> None:
    bad = [{"id": "opening", "outcome": "4", "rationale": "r",
            "evidence": [{"turn_index": 2, "quote": "We already have Gong"}]}]
    good_next = {"id": "next_step", "outcome": "4", "rationale": "r",
                 "evidence": [{"turn_index": 3, "quote": "book Tuesday at ten"}]}
    scorer = ScriptedScorer([bad + [good_next], bad, bad])
    raw, failed, calls = await run_scoring(scorer, criteria=CRITERIA, turns=TURNS,
                                           buyer_name="Priya", scenario_title="t")
    assert len(calls) == 3  # first call + MAX_VERIFY_RETRIES
    assert [f.reason for f in failed] == ["misattributed"]


async def test_omitted_criterion_is_asked_for_again() -> None:
    scorer = ScriptedScorer([
        [{"id": "opening", "outcome": "2", "rationale": "r",
          "evidence": [{"turn_index": 1, "quote": "Arjun from HyperSale"}]}],
        [{"id": "next_step", "outcome": "insufficient_evidence", "rationale": "r", "evidence": []}],
    ])
    raw, failed, _ = await run_scoring(scorer, criteria=CRITERIA, turns=TURNS,
                                       buyer_name="Priya", scenario_title="t")
    assert {c["id"] for c in raw} == {"opening", "next_step"} and failed == []
    assert "omitted" in scorer.calls[1]["user"]


def test_drills_target_the_weakest_scored_criteria() -> None:
    scored = [{"id": "opening", "score": 4}, {"id": "discovery", "score": 1},
              {"id": "value", "score": None}, {"id": "next_step", "score": 2}]
    assert pick_drill_criteria(scored, ["opening", "discovery", "value", "next_step"]) == [
        "discovery", "next_step", "opening"]


async def test_six_criteria_are_scored_two_per_parallel_call() -> None:
    ids = ["opening", "discovery", "listening", "value", "objection_handling", "next_step"]
    criteria = [Criterion(i, i, "d") for i in ids]

    class Echo:
        model_id = "fake"
        def __init__(self):
            self.groups = []
        async def score(self, *, system, user, tool, turns):
            group = tool["input_schema"]["properties"]["criteria"]["items"]["properties"]["id"]["enum"]
            self.groups.append(list(group))
            return ScorerResult([{"id": g, "outcome": "insufficient_evidence", "rationale": "r",
                                  "evidence": []} for g in group], "fake", 10, 10, 0, 5)

    scorer = Echo()
    raw, failed, calls = await run_scoring(scorer, criteria=criteria, turns=TURNS,
                                           buyer_name="P", scenario_title="t")
    assert scorer.groups == [ids[0:2], ids[2:4], ids[4:6]] and len(calls) == 3
    assert {c["id"] for c in raw} == set(ids) and failed == []
