"""Deterministic call metrics (PRD §3.3): computed in code, instant, and never by a model.

`METRICS_VERSION` is part of every score's provenance (D16); change any formula here and
bump it, or old and new reports silently stop being comparable.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Protocol

METRICS_VERSION = "metrics-v1"

FILLERS = ("um", "uh", "like", "you know", "basically", "actually", "kind of", "sort of")
_FILLER_RE = re.compile(r"\b(" + "|".join(re.escape(f) for f in FILLERS) + r")\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_DAY_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next week|"
    r"\d{1,2}(:\d{2})?\s*(am|pm)|\d{1,2}(st|nd|rd|th)|january|february|march|april|may|june|"
    r"july|august|september|october|november|december)\b",
    re.IGNORECASE,
)
_ASK_RE = re.compile(
    r"\b(book|schedule|set up|meet|call|demo|walkthrough|invite|calendar|follow[- ]up)\b",
    re.IGNORECASE,
)
_OPEN_Q_RE = re.compile(r"^\s*(how|what|why|walk me|tell me|describe|which|where|when|who)\b",
                        re.IGNORECASE)


class Turn(Protocol):
    speaker: str
    text: str
    start_ms: int
    end_ms: int


def _words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _questions(text: str) -> list[str]:
    # Sentences ending in '?' are questions; split so one turn can hold several.
    return [s.strip() for s in re.findall(r"[^.?!]*\?", text) if s.strip()]


def compute_metrics(turns: Sequence[Turn]) -> dict[str, Any]:
    rep = [t for t in turns if t.speaker == "rep"]
    buyer = [t for t in turns if t.speaker == "buyer"]
    rep_words = sum(_words(t.text) for t in rep)
    buyer_words = sum(_words(t.text) for t in buyer)
    total_words = rep_words + buyer_words

    questions = [q for t in rep for q in _questions(t.text)]
    open_questions = [q for q in questions if _OPEN_Q_RE.match(q)]
    longest = max(rep, key=lambda t: _words(t.text), default=None)
    fillers = sum(len(_FILLER_RE.findall(t.text)) for t in rep)
    next_step = next(
        (t for t in rep if "?" in t.text and _ASK_RE.search(t.text) and _DAY_RE.search(t.text)),
        None,
    )
    duration_ms = max((t.end_ms for t in turns), default=0) - min((t.start_ms for t in turns), default=0)

    return {
        "metrics_version": METRICS_VERSION,
        "turns": len(turns),
        "rep_turns": len(rep),
        "buyer_turns": len(buyer),
        "duration_ms": max(0, duration_ms),
        # Word share is robust to VAD timing noise, unlike speaking-time share.
        "talk_ratio_rep": round(rep_words / total_words, 3) if total_words else None,
        "rep_words": rep_words,
        "buyer_words": buyer_words,
        "questions": len(questions),
        "open_questions": len(open_questions),
        "longest_monologue_words": _words(longest.text) if longest else 0,
        "filler_words": fillers,
        "fillers_per_100_words": round(100 * fillers / rep_words, 2) if rep_words else 0.0,
        "next_step_with_date": next_step is not None,
        "next_step_quote": next_step.text if next_step else None,
    }
