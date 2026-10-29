"""AI rep for the live smoke (D34): hears the buyer, answers, and differs every call.

The browser's microphone is replaced by a Web Audio stream (`INIT_JS`), so each rep line can
be synthesised after the buyer has spoken and played into the call. An analyser on the remote
WebRTC track tells us when the buyer has stopped talking, so the rep does not barge in. The
rep's words come from REP_SIM_MODEL through the app's own adapter client (RULES: no provider
SDK outside `adapters/`). Test harness only: it touches product data only by speaking.
"""
from __future__ import annotations

import base64
import importlib
import json
import random
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

# The backend is put on sys.path by the caller (live_smoke); imported here, not at the top, so
# the two Ruff configs (root and services/backend) agree on import order.
llm_client = importlib.import_module("app.adapters.llm.client")
llm_models = importlib.import_module("app.adapters.llm.models")
REP_SIM_MODEL = llm_models.REP_SIM_MODEL

# Replaces getUserMedia with a Web Audio destination and taps the buyer's remote audio.
INIT_JS = """
(() => {
  const ctx = new AudioContext({ sampleRate: 48000 });
  const dest = ctx.createMediaStreamDestination();
  // A near-silent carrier keeps the track live between rep lines.
  const carrier = ctx.createConstantSource(); const g = ctx.createGain();
  g.gain.value = 0.0001; carrier.connect(g).connect(dest); carrier.start();
  window.__rep = { speakingUntil: 0, buyerAnalyser: null };
  navigator.mediaDevices.getUserMedia = async (c) => {
    if (c && c.video) throw new DOMException('no video', 'NotFoundError');
    await ctx.resume();
    return new MediaStream(dest.stream.getAudioTracks().map((t) => t.clone()));
  };
  window.__repSay = async (b64) => {
    await ctx.resume();
    const bytes = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
    const buf = await ctx.decodeAudioData(bytes.buffer);
    const src = ctx.createBufferSource(); src.buffer = buf; src.connect(dest);
    const start = Math.max(ctx.currentTime, 0) + 0.05; src.start(start);
    window.__rep.speakingUntil = performance.now() + (buf.duration + 0.05) * 1000;
    return buf.duration;
  };
  window.__buyerLevel = () => {
    const a = window.__rep.buyerAnalyser; if (!a) return -1;
    const d = new Float32Array(a.fftSize); a.getFloatTimeDomainData(d);
    let s = 0; for (const v of d) s += v * v; return Math.sqrt(s / d.length);
  };
  const Native = window.RTCPeerConnection;
  window.RTCPeerConnection = class extends Native {
    constructor(...args) {
      super(...args);
      this.addEventListener('track', (e) => {
        if (e.track.kind !== 'audio') return;
        const a = ctx.createAnalyser(); a.fftSize = 2048;
        ctx.createMediaStreamSource(new MediaStream([e.track])).connect(a);  // not to dest: no echo
        window.__rep.buyerAnalyser = a;
      });
    }
  };
})();
"""

READ_TRANSCRIPT_JS = """() => Array.from(document.querySelectorAll('[data-testid=live-transcript] li.rep, [data-testid=live-transcript] li.buyer'))
  .map((li) => { const s = li.querySelector('span:last-child'); return { speaker: li.className, text: s.textContent, final: !s.classList.contains('muted') }; })"""

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
VOICES = {"male": "Microsoft David Desktop", "female": "Microsoft Zira Desktop"}
FEMALE = {"Maya", "Sara"}

MAX_REP_TURNS = 14
BUYER_SILENCE_S = 0.9   # buyer audio quiet this long = their turn is over
BUYER_LEVEL = 0.012     # RMS above this = the buyer is talking
NUDGE_AFTER_S = 7.0     # nobody talking this long: the rep carries on


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
class RepLog:
    lines: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        fresh_in, _, out = llm_models.MODEL_PRICES_MICROUSD_PER_1M[REP_SIM_MODEL]
        return (self.input_tokens * fresh_in + self.output_tokens * out) / 1e12


class SapiVoice:
    """One long-lived PowerShell running System.Speech; ~0.5 s per line instead of ~2 s."""

    def __init__(self, work: Path, voice: str) -> None:
        script = work / "sapi_server.ps1"
        script.write_text(f"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{ $s.SelectVoice('{voice}') }} catch {{ }}
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(48000, `
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
while (($line = [Console]::In.ReadLine()) -ne $null) {{
  $req = $line | ConvertFrom-Json
  $s.SetOutputToWaveFile($req.path, $fmt); $s.Speak($req.text); $s.SetOutputToNull()
  [Console]::Out.WriteLine('OK'); [Console]::Out.Flush()
}}
""", encoding="utf-8")
        self.work = work
        self.n = 0
        self.proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)

    def wav(self, text: str) -> bytes:
        path = self.work / f"rep_{self.n:02d}.wav"
        self.n += 1
        self.proc.stdin.write(json.dumps({"text": text, "path": str(path)}) + "\n")
        self.proc.stdin.flush()
        if self.proc.stdout.readline().strip() != "OK":
            raise RuntimeError("SAPI voice server died")
        return path.read_bytes()

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait(timeout=10)


class RepBrain:
    def __init__(self, scenario: dict[str, Any], profile: RepProfile) -> None:
        self.client = llm_client.build_client(model_id=REP_SIM_MODEL)
        self.system = (
            f"You are {profile.name}, a sales rep at HyperSale, on a live phone call. Your words "
            f"are spoken aloud by text-to-speech, so write exactly what you say next and nothing "
            f"else: no stage directions, quotes, lists or emojis, one or two short sentences, at "
            f"most 25 words.\n\nProduct: {PRODUCT}\n\nCall: {scenario['title']}. Brief: "
            f"{scenario['brief']}\n\nYour style: {SKILLS[profile.skill]} Opening angle: "
            f"{profile.angle}.\n\nWhen the call has reached its natural end (a next step is "
            f"agreed, the buyer firmly ends it, or you have said goodbye), finish your line with "
            f"[END]."
        )

    def next_line(self, history: list[dict[str, str]], log: RepLog) -> tuple[str, bool]:
        convo = "\n".join(f"{'YOU' if h['speaker'] == 'rep' else 'BUYER'}: {h['text']}" for h in history)
        prompt = (f"Conversation so far:\n{convo}\n\nWhat do you say next?" if history
                  else "The buyer has just picked up and said nothing yet. What do you say first?")
        started = time.perf_counter()
        text = ""
        # The model reasons before answering; a reply can come back empty when reasoning eats
        # the budget. Ask again rather than putting words in the rep's mouth.
        for _ in range(2):
            resp = self.client.messages.create(model=REP_SIM_MODEL, max_tokens=2000, system=self.system,
                                               messages=[{"role": "user", "content": prompt}])
            log.input_tokens += resp.usage.input_tokens or 0
            log.output_tokens += resp.usage.output_tokens or 0
            text = " ".join(b.text for b in resp.content if b.type == "text").strip()
            if text.replace("[END]", "").strip():
                break
        ended = "[END]" in text
        text = text.replace("[END]", "").strip().strip('"')
        log.lines.append({"text": text, "llm_ms": int((time.perf_counter() - started) * 1000), "end": ended})
        return text, ended


def spoken(text: str) -> str:
    """TTS pauses at sentence ends long enough for the buyer's VAD to end the rep's turn, so
    mid-line sentence breaks are spoken as commas; the final punctuation is kept."""
    return re.sub(r"(?<=\w)[.!?;:]\s+(?=\S)", ", ", text)


def _wait_for_buyer_turn(page: Page, since_buyer: int, deadline: float) -> None:
    """Return once the buyer has spoken and gone quiet, or nobody has talked for a while."""
    quiet_since = time.time()
    while time.time() < deadline:
        level = page.evaluate("() => window.__buyerLevel()")
        speaking = level > BUYER_LEVEL
        quiet_since = time.time() if speaking else quiet_since
        quiet_for = time.time() - quiet_since
        finals = [t for t in page.evaluate(READ_TRANSCRIPT_JS) if t["speaker"] == "buyer" and t["final"]]
        if len(finals) > since_buyer and quiet_for >= BUYER_SILENCE_S:
            return
        if quiet_for >= NUDGE_AFTER_S:
            return
        time.sleep(0.15)


def run_ai_call(page: Page, scenario: dict[str, Any], profile: RepProfile, work: Path,
                max_seconds: float) -> RepLog:
    """Talk until the rep ends the call, the turn cap, or the time budget. Caller hangs up."""
    voice = SapiVoice(work, VOICES["female" if profile.name in FEMALE else "male"])
    brain, log = RepBrain(scenario, profile), RepLog()
    history: list[dict[str, str]] = []
    seen_buyer = 0
    deadline = time.time() + max_seconds
    try:
        _wait_for_buyer_turn(page, 0, time.time() + 5)  # let the buyer answer the phone first
        for _ in range(MAX_REP_TURNS):
            buyers = [t for t in page.evaluate(READ_TRANSCRIPT_JS) if t["speaker"] == "buyer" and t["final"]]
            history.extend({"speaker": "buyer", "text": t["text"]} for t in buyers[seen_buyer:])
            seen_buyer = len(buyers)
            text, ended = brain.next_line(history, log)
            if not text:
                _wait_for_buyer_turn(page, seen_buyer, deadline + 10)
                continue
            history.append({"speaker": "rep", "text": text})
            audio = base64.b64encode(voice.wav(spoken(text))).decode()
            duration = page.evaluate("(b) => window.__repSay(b)", audio)
            log.lines[-1]["audio_s"] = round(duration, 2)
            time.sleep(duration + 0.2)
            if ended:
                time.sleep(4)  # let the buyer say goodbye
                break
            if time.time() > deadline:
                break
            _wait_for_buyer_turn(page, seen_buyer, deadline + 10)
    finally:
        voice.close()
    return log
