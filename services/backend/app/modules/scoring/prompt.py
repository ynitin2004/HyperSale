"""Scoring prompt and output schema. `SCORING_PROMPT_VERSION` is provenance (D16): any edit
to the text or schema below bumps it, so a report always names the exact prompt behind it.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

SCORING_PROMPT_VERSION = "score-v1-2026-10-29"
TOOL_NAME = "submit_scores"


def build_tool(criterion_ids: Sequence[str]) -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": "Submit one score with verbatim evidence for every listed criterion.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["criteria"],
            "properties": {
                "criteria": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "outcome", "rationale", "evidence"],
                        "properties": {
                            "id": {"type": "string", "enum": list(criterion_ids)},
                            "outcome": {
                                "type": "string",
                                "enum": ["1", "2", "3", "4", "5", "insufficient_evidence"],
                            },
                            "rationale": {"type": "string", "maxLength": 500},
                            "evidence": {
                                "type": "array",
                                "maxItems": 3,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["turn_index", "quote"],
                                    "properties": {
                                        "turn_index": {"type": "integer", "minimum": 0},
                                        "quote": {"type": "string", "minLength": 3, "maxLength": 300},
                                    },
                                },
                            },
                        },
                    },
                }
            },
        },
    }


def build_system(criteria: Sequence[Any], *, buyer_name: str, scenario_title: str) -> str:
    lines = "\n".join(f"- {c.id} ({c.name}): {c.description}" for c in criteria)
    return f"""You score a sales rep's practice call against a rubric. Only the REP is scored.
The buyer ({buyer_name}) is an AI persona and is never scored. Scenario: {scenario_title}.

Rules:
- Return exactly one entry for EVERY criterion listed below, and no others.
- Give a 1-5 score only when rep turns bear on the criterion, and cite 1-3 pieces of evidence.
- Every quote MUST be copied verbatim (at least two words) from the REP turn whose index you
  cite. Never cite a BUYER turn as evidence of what the rep did.
- If the call never reached a point where the criterion could be observed, answer
  "insufficient_evidence" with an empty evidence list. Do not guess.
- Scale: 1 absent or harmful, 2 weak, 3 adequate, 4 strong, 5 exemplary. Generic, vague
  statements earn 1-2.
- The rationale is one or two sentences, addressed to the rep, saying what to do differently.

Criteria:
{lines}"""


def render_transcript(turns: Sequence[Any]) -> str:
    body = "\n".join(f"[{t.idx}] {t.speaker.upper()}: {t.text}" for t in turns)
    return f"Transcript (turn index, speaker, text):\n{body}"


def render_feedback(failed: Sequence[Any]) -> str:
    """Retry prompt after verification rejected quotes (D13 retry-then-degrade)."""
    lines = []
    for f in failed:
        why = {
            "fabricated": "does not appear in that turn",
            "misattributed": f"is in a {f.speaker} turn, not a rep turn",
            "bad_turn": "cites a turn index that does not exist",
            "too_short": "is too short to verify",
        }.get(f.reason, "failed verification")
        lines.append(f"- {f.criterion_id}: turn {f.turn_index} quote \"{f.quote}\" {why}")
    return (
        "Some evidence failed verification:\n" + "\n".join(lines) +
        "\nResubmit ONLY these criteria. Copy quotes character for character from REP turns, "
        "or use insufficient_evidence if no rep turn supports a score."
    )
