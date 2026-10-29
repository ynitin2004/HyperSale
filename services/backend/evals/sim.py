"""Text-only simulated calls for the gold set (D36), and the rep prompt the voice smoke shares (D34).

An AI rep of a drawn skill talks to an AI buyer that runs the *seeded* persona instructions.
Both go through the app's adapter client (RULES: no provider SDK outside `adapters/`). The
transcript has the same shape the scorer sees: indexed rep/buyer turns.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any

from app.adapters.llm.client import build_client
from app.adapters.llm.models import MODEL_PRICES_MICROUSD_PER_1M, REP_SIM_MODEL
from app.modules.catalog.seed import PersonaSeed

PRODUCT = (
    "HyperSale: AI voice roleplay so reps practise against realistic buyers before real calls, "
    "plus scoring where every score cites the exact quote behind it. Typical pricing: $90 per "
    "rep per month on an annual plan; a 30-day pilot for one team is available. Managers see "
    "who is improving week by week instead of finding out at quota time."
)
SKILLS = {
    "weak": ("You are a new, nervous rep. Pitch features early and talk more than you listen. "
             "Ask few questions, mostly closed ones. Dodge the first price question. Do not build "
             "on what the buyer just said. Your next step is vague."),
    "average": ("You are a competent rep with gaps. Reasonable opener, two or three discovery "
                "questions with shallow follow-up, partial objection handling, and a next step "
                "without a firm date unless the buyer pushes."),
    "strong": ("You are a top rep. Ask permission and give a specific reason in the opener. Ask "
               "open questions that build on the buyer's own words, quantify the pain, answer "
               "price directly, acknowledge and reframe objections, and close on a specific next "
               "step with day, time and attendees."),
}
ANGLES = [
    "lead with rep attrition", "lead with new-hire ramp time", "lead with manager coaching time",
    "lead with a peer company's result", "lead with a recent hiring push you noticed",
]
REP_NAMES = ["Arjun", "Maya", "Leo", "Rohan", "Sara", "Dev"]
END = "[END]"


@dataclass
class RepProfile:
    seed: int
    skill: str
    angle: str
    name: str

    @classmethod
    def draw(cls, seed: int | None = None, skill: str | None = None) -> RepProfile:
        seed = seed if seed is not None else random.SystemRandom().randrange(1_000_000)
        rng = random.Random(seed)
        return cls(seed, skill or rng.choice(sorted(SKILLS)), rng.choice(ANGLES), rng.choice(REP_NAMES))


@dataclass
class Spend:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    @property
    def cost_usd(self) -> float:
        fresh_in, _, out = MODEL_PRICES_MICROUSD_PER_1M[REP_SIM_MODEL]
        return (self.input_tokens * fresh_in + self.output_tokens * out) / 1e12


def rep_system(scenario: dict[str, Any], profile: RepProfile) -> str:
    return (
        f"You are {profile.name}, a sales rep at HyperSale, on a live phone call. Your words are "
        f"spoken aloud, so write exactly what you say next and nothing else: no stage directions, "
        f"quotes, lists or emojis, one or two short sentences, at most 25 words.\n\n"
        f"Product: {PRODUCT}\n\nCall: {scenario['title']}. Brief: {scenario['brief']}\n\n"
        f"Your style: {SKILLS[profile.skill]} Opening angle: {profile.angle}.\n\n"
        f"When the call has reached its natural end (a next step is agreed, the buyer firmly ends "
        f"it, or you have said goodbye), finish your line with {END}."
    )


def buyer_system(persona: PersonaSeed) -> str:
    return (
        f"{persona.instructions}\n\nThis call is carried as text. Reply with only the words you "
        f"say next, as {persona.name} would say them aloud: no stage directions, no narration. "
        f"If you hang up or the call is over, finish your line with {END}."
    )


def _render(history: list[dict[str, str]], me: str) -> str:
    return "\n".join(f"{'YOU' if h['speaker'] == me else ('REP' if me == 'buyer' else 'BUYER')}: "
                     f"{h['text']}" for h in history)


class Speaker:
    """One side of the call. Retries an empty reply (reasoning can eat the budget)."""

    def __init__(self, system: str, role: str, spend: Spend) -> None:
        self.client = build_client(model_id=REP_SIM_MODEL)
        self.system, self.role, self.spend = system, role, spend

    def say(self, history: list[dict[str, str]], first_prompt: str) -> tuple[str, bool, int]:
        prompt = (f"Conversation so far:\n{_render(history, self.role)}\n\nWhat do you say next?"
                  if history else first_prompt)
        started = time.perf_counter()
        text = ""
        for _ in range(2):
            resp = self.client.messages.create(model=REP_SIM_MODEL, max_tokens=2000, system=self.system,
                                               messages=[{"role": "user", "content": prompt}])
            self.spend.calls += 1
            self.spend.input_tokens += resp.usage.input_tokens or 0
            self.spend.output_tokens += resp.usage.output_tokens or 0
            text = " ".join(b.text for b in resp.content if b.type == "text").strip()
            if text.replace(END, "").strip():
                break
        ended = END in text
        return text.replace(END, "").strip().strip('"'), ended, int((time.perf_counter() - started) * 1000)


@dataclass
class SimCall:
    scenario: str
    persona: str
    profile: RepProfile
    turns: list[dict[str, Any]] = field(default_factory=list)
    spend: Spend = field(default_factory=Spend)


def simulate(scenario: dict[str, Any], persona: PersonaSeed, profile: RepProfile,
             max_rep_turns: int = 7) -> SimCall:
    """Buyer answers the phone, then rep and buyer alternate until [END] or the turn cap."""
    call = SimCall(scenario["slug"], persona.slug, profile)
    rep = Speaker(rep_system(scenario, profile), "rep", call.spend)
    buyer = Speaker(buyer_system(persona), "buyer", call.spend)
    history: list[dict[str, str]] = []
    greeting, _, _ = buyer.say([], "Your phone rings and you pick up. What do you say?")
    history.append({"speaker": "buyer", "text": greeting})
    for _ in range(max_rep_turns):
        line, rep_ended, _ = rep.say(history, "")
        if line:
            history.append({"speaker": "rep", "text": line})
        reply, buyer_ended, _ = buyer.say(history, "")
        if reply:
            history.append({"speaker": "buyer", "text": reply})
        if rep_ended or buyer_ended:
            break
    call.turns = [{"idx": i, **h} for i, h in enumerate(history)]
    return call
