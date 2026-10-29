"""D13's two code-enforced evidence checks. The single most important file in the product.

A quote is accepted only if
  * EXISTENCE: after normalisation it appears inside the turn it cites, and
  * ATTRIBUTION: that turn was spoken by the rep.
Misattributing the buyer's words to the rep is the most damaging failure this product can
make (D13), so a quote that exists but sits in a buyer turn is rejected, never "repaired".
Relevance (does the quote support the claim?) is not checkable here and is measured by
sampled human review in M2 - never claimed zero.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

MIN_QUOTE_WORDS = 2


class Turn(Protocol):
    idx: int
    speaker: str
    text: str
    start_ms: int
    end_ms: int


def normalize(text: str) -> str:
    text = text.casefold().replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class EvidenceCheck:
    criterion_id: str
    turn_index: int
    quote: str
    ok: bool
    reason: str | None = None  # "fabricated" | "misattributed" | "too_short" | "bad_turn"
    speaker: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass
class VerificationResult:
    checks: list[EvidenceCheck] = field(default_factory=list)

    @property
    def failed(self) -> list[EvidenceCheck]:
        return [c for c in self.checks if not c.ok]

    @property
    def fabricated(self) -> int:
        return sum(1 for c in self.checks if c.reason in ("fabricated", "bad_turn", "too_short"))

    @property
    def misattributed(self) -> int:
        return sum(1 for c in self.checks if c.reason == "misattributed")


def check_quote(criterion_id: str, turn_index: int, quote: str, turns: Sequence[Turn]) -> EvidenceCheck:
    by_idx = {t.idx: t for t in turns}
    turn = by_idx.get(turn_index)
    if turn is None:
        return EvidenceCheck(criterion_id, turn_index, quote, False, "bad_turn")
    needle = normalize(quote)
    if len(needle.split()) < MIN_QUOTE_WORDS:
        return EvidenceCheck(criterion_id, turn_index, quote, False, "too_short")
    if needle not in normalize(turn.text):
        return EvidenceCheck(criterion_id, turn_index, quote, False, "fabricated")
    if turn.speaker != "rep":
        return EvidenceCheck(criterion_id, turn_index, quote, False, "misattributed", turn.speaker)
    return EvidenceCheck(criterion_id, turn_index, quote, True, None, turn.speaker,
                         turn.start_ms, turn.end_ms)


def verify(criteria: Sequence[dict[str, Any]], turns: Sequence[Turn]) -> VerificationResult:
    result = VerificationResult()
    for crit in criteria:
        for ev in crit.get("evidence") or []:
            result.checks.append(
                check_quote(crit["id"], int(ev.get("turn_index", -1)), str(ev.get("quote", "")), turns)
            )
    return result
