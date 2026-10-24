"""Automated driver for voice-live-webrtc.html — closes the M0 voice gates without a human.

What it proves, in one Azure Voice Live session:
  1. CONTROL CHANNEL: drops the signalling WebSocket after N turns and counts the turns that
     still complete over the data channel. Any post-drop turn means the adapter can be
     fire-and-forget (ARCHITECTURE §4 / D21 lifecycle question).
  2. AUDIO TRUTH: the mixed mic+remote MediaRecorder output is decoded with ffmpeg and
     checked for energy inside BOTH the rep's speech windows and the buyer's response
     windows, so "both voices present" is measured rather than listened for.
  3. LATENCY: speech_stopped -> first transcript delta (the harness metric) AND
     speech_stopped -> first audible remote energy (the metric the product budget means).
  4. COST TRUTH: sums `response.done.usage` token details and prices them with the rates
     passed in, writing a report the usage ledger can ingest.

The "rep" is Windows SAPI text-to-speech rendered to a WAV that Chromium plays as a fake
microphone (--use-file-for-fake-audio-capture). Silence gaps between lines give the buyer
room to answer; server VAD does the turn-taking exactly as it would with a human.

Usage (from the repo root, with AZURE_VOICE_LIVE_* in .env):
  services/backend/.venv/Scripts/python.exe spikes/run_voice_spike.py --browser chromium
  services/backend/.venv/Scripts/python.exe spikes/run_voice_spike.py --browser msedge --headed
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import subprocess
import sys
import threading
import time
import wave
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SPIKES = ROOT / "spikes"
SAMPLE_RATE = 48_000

# A believable cold call against Priya. Short lines, because she interrupts ramblers.
REP_LINES = [
    "Hi Priya, this is Arjun from HyperSale. I know you didn't ask for this call, so I'll be quick.",
    ("I'm calling because freight brokerages like Meridian lose two or three reps a quarter, "
     "and most of those were coachable before they missed quota."),
    ("We record practice calls and score them against evidence, so you can see which reps are "
     "coachable in week two instead of month four."),
    ("Totally fair. Ride-alongs are great, but they don't scale to sixty reps, and the notes "
     "live in a manager's head. We give you the same signal from recorded calls."),
    ("I hear that about Gong a lot. It records real calls after the fact and hands managers more "
     "to read. We give reps practice before the call, and a score with the exact quote behind it."),
    "Most teams start under fifty thousand a year, which I believe sits inside your authority.",
    ("I understand Daniel owns the final call. Would a twenty minute walkthrough with both of "
     "you next Tuesday be a reasonable next step?"),
    "What would you need to see in that walkthrough for it to be worth Daniel's twenty minutes?",
    "Understood. Which two reps would you say are on the bubble right now?",
    "That's exactly the case we built this for. I'll keep the walkthrough to those two reps.",
    "Great, I'll send an invite for Tuesday at ten. Thanks for the time, Priya.",
]
# Seconds of silence after each rep line; Priya speaks one or two sentences in this window.
GAP_SECONDS = 8.0
LEAD_IN_SECONDS = 2.5

# Default rates: USD per 1M tokens for gpt-realtime. Override with --rates '{"audio_in": ..}'.
# Keys: text_in, text_in_cached, audio_in, audio_in_cached, text_out, audio_out.
DEFAULT_RATES_USD_PER_M = {
    "text_in": 4.0,
    "text_in_cached": 0.40,
    "audio_in": 32.0,
    "audio_in_cached": 0.40,
    "text_out": 16.0,
    "audio_out": 64.0,
    "source": "default (unverified) — pass --rates with the Azure pricing page values",
}


# --------------------------------------------------------------------------- rep audio


def synthesize_rep_wav(out_dir: Path, voice: str) -> tuple[Path, list[dict]]:
    """Render REP_LINES with SAPI into one 48 kHz mono 16-bit WAV with silence gaps.

    Returns the WAV path and the planned timeline of rep segments (seconds).
    """
    lines_json = out_dir / "rep_lines.json"
    lines_json.write_text(json.dumps(REP_LINES), encoding="utf-8")
    ps_script = out_dir / "tts.ps1"
    ps_script.write_text(
        f"""
Add-Type -AssemblyName System.Speech
$lines = Get-Content -Raw -Encoding UTF8 '{lines_json}' | ConvertFrom-Json
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{ $s.SelectVoice('{voice}') }} catch {{ }}
$s.Rate = 0
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo({SAMPLE_RATE}, `
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, `
    [System.Speech.AudioFormat.AudioChannel]::Mono)
$i = 0
foreach ($line in $lines) {{
  $s.SetOutputToWaveFile((Join-Path '{out_dir}' ("line_$i.wav")), $fmt)
  $s.Speak($line)
  $i++
}}
$s.Dispose()
""",
        encoding="utf-8",
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps_script)],
        check=True,
        capture_output=True,
    )

    rep_wav = out_dir / "rep.wav"
    timeline: list[dict] = []
    with wave.open(str(rep_wav), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(b"\x00\x00" * int(LEAD_IN_SECONDS * SAMPLE_RATE))
        cursor = LEAD_IN_SECONDS
        for i, line in enumerate(REP_LINES):
            with wave.open(str(out_dir / f"line_{i}.wav"), "rb") as src:
                assert src.getframerate() == SAMPLE_RATE and src.getnchannels() == 1
                frames = src.readframes(src.getnframes())
            seconds = len(frames) / 2 / SAMPLE_RATE
            timeline.append({"index": i, "start": cursor, "end": cursor + seconds, "text": line})
            out.writeframes(frames)
            out.writeframes(b"\x00\x00" * int(GAP_SECONDS * SAMPLE_RATE))
            cursor += seconds + GAP_SECONDS
    return rep_wav, timeline


# --------------------------------------------------------------------------- static server


def serve_spikes() -> tuple[ThreadingHTTPServer, str]:
    handler = partial(SimpleHTTPRequestHandler, directory=str(SPIKES))
    handler.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/voice-live-webrtc.html"


# --------------------------------------------------------------------------- browser hooks

# Installed before the page script runs: timestamps recorder start and captures the
# remote track so audible onset can be measured independently of the transcript.
INIT_SCRIPT = """
window.__ev = [];
window.__push = (type, extra) => window.__ev.push(Object.assign({t: performance.now(), type}, extra || {}));
const _start = MediaRecorder.prototype.start;
MediaRecorder.prototype.start = function (...args) {
  window.__push('recorder.start');
  return _start.apply(this, args);
};
const _srcObject = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'srcObject');
Object.defineProperty(HTMLMediaElement.prototype, 'srcObject', {
  set(stream) {
    _srcObject.set.call(this, stream);
    if (stream && !window.__analyser) {
      try {
        const ctx = new AudioContext();
        const src = ctx.createMediaStreamSource(stream);
        const an = ctx.createAnalyser(); an.fftSize = 1024;
        src.connect(an);
        const buf = new Float32Array(an.fftSize);
        let loud = false;
        window.__analyser = setInterval(() => {
          an.getFloatTimeDomainData(buf);
          let s = 0; for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
          const rms = Math.sqrt(s / buf.length);
          const nowLoud = rms > 0.01;
          if (nowLoud && !loud) window.__push('remote.audio.onset', {rms});
          if (!nowLoud && loud) window.__push('remote.audio.end', {rms});
          loud = nowLoud;
        }, 10);
        window.__push('remote.analyser.attached');
      } catch (e) { window.__push('remote.analyser.error', {message: String(e)}); }
    }
  },
  get() { return _srcObject.get.call(this); },
});
"""

# Installed after the page script defined onEvent: records every server event compactly.
HOOK_SCRIPT = """
() => {
  const orig = window.onEvent;
  window.onEvent = (m) => {
    const rec = {};
    if (m.type === 'response.done' && m.response) rec.usage = m.response.usage || null;
    if (m.type === 'response.audio_transcript.done') rec.transcript = m.transcript;
    if (m.type === 'conversation.item.input_audio_transcription.completed') rec.transcript = m.transcript;
    if (m.type === 'error' || m.type === 'rtc.call.error') rec.error = m.error || m;
    window.__push(m.type, rec);
    return orig(m);
  };
  return true;
}
"""

READ_RECORDING = """
async () => {
  if (!chunks.length) return null;
  const blob = new Blob(chunks, {type: chunks[0].type || 'audio/webm'});
  const buf = await blob.arrayBuffer();
  // Decode in the browser: 100 ms RMS windows are all the analysis needs, and it avoids
  // depending on an ffmpeg build that may lack the codec.
  let rms = null, duration = null, decodeError = null;
  try {
    const ctx = new AudioContext();
    const audio = await ctx.decodeAudioData(buf.slice(0));
    duration = audio.duration;
    const ch = audio.getChannelData(0);
    const win = Math.round(audio.sampleRate / 10);
    rms = [];
    for (let i = 0; i + win <= ch.length; i += win) {
      let s = 0; for (let j = i; j < i + win; j++) s += ch[j] * ch[j];
      rms.push(Math.sqrt(s / win));
    }
    ctx.close();
  } catch (e) { decodeError = String(e); }
  const bytes = new Uint8Array(buf);
  let s = ''; const CH = 0x8000;
  for (let i = 0; i < bytes.length; i += CH) s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  return {type: blob.type, b64: btoa(s), size: bytes.length, duration, rms, decodeError};
}
"""


# --------------------------------------------------------------------------- analysis


def mean_rms_in(windows: list[float], spans: list[tuple[float, float]], window_ms: int = 100) -> float:
    vals = []
    for start, end in spans:
        a, b = int(start * 1000 / window_ms), int(end * 1000 / window_ms)
        vals.extend(windows[max(0, a) : max(0, b)])
    return sum(vals) / len(vals) if vals else 0.0


def price(usage_totals: dict, rates: dict) -> dict:
    def per_m(key: str, tokens: int) -> float:
        return tokens * rates[key] / 1_000_000

    cost = {
        "text_in": per_m("text_in", usage_totals["text_in"]),
        "text_in_cached": per_m("text_in_cached", usage_totals["text_in_cached"]),
        "audio_in": per_m("audio_in", usage_totals["audio_in"]),
        "audio_in_cached": per_m("audio_in_cached", usage_totals["audio_in_cached"]),
        "text_out": per_m("text_out", usage_totals["text_out"]),
        "audio_out": per_m("audio_out", usage_totals["audio_out"]),
    }
    cost["total_usd"] = round(sum(cost.values()), 6)
    cost["total_microusd"] = round(cost["total_usd"] * 1_000_000)
    return cost


def summarize_usage(events: list[dict]) -> dict:
    totals = {k: 0 for k in ("text_in", "text_in_cached", "audio_in", "audio_in_cached",
                             "text_out", "audio_out", "input_tokens", "output_tokens")}
    responses = 0
    for e in events:
        u = e.get("usage")
        if not u:
            continue
        responses += 1
        ind = u.get("input_token_details") or {}
        outd = u.get("output_token_details") or {}
        cached = ind.get("cached_tokens_details") or {}
        cached_text = cached.get("text_tokens", 0) or 0
        cached_audio = cached.get("audio_tokens", 0) or 0
        totals["text_in"] += (ind.get("text_tokens", 0) or 0) - cached_text
        totals["audio_in"] += (ind.get("audio_tokens", 0) or 0) - cached_audio
        totals["text_in_cached"] += cached_text
        totals["audio_in_cached"] += cached_audio
        totals["text_out"] += outd.get("text_tokens", 0) or 0
        totals["audio_out"] += outd.get("audio_tokens", 0) or 0
        totals["input_tokens"] += u.get("input_tokens", 0) or 0
        totals["output_tokens"] += u.get("output_tokens", 0) or 0
    totals["responses"] = responses
    return totals


# --------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", choices=["chromium", "msedge", "chrome"], default="chromium")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--drop-after", type=int, default=3, help="drop signalling WS after N turns")
    ap.add_argument("--max-seconds", type=int, default=150)
    ap.add_argument("--voice", default="Microsoft David Desktop")
    ap.add_argument("--rates", default=None, help="JSON of USD-per-1M-token rates")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    api_key = env.get("AZURE_VOICE_LIVE_API_KEY")
    endpoint = env.get("AZURE_VOICE_LIVE_ENDPOINT")
    model = env.get("AZURE_VOICE_LIVE_MODEL", "gpt-realtime")
    if not api_key or not endpoint:
        print("AZURE_VOICE_LIVE_API_KEY / AZURE_VOICE_LIVE_ENDPOINT missing in .env", file=sys.stderr)
        return 2
    rates = dict(DEFAULT_RATES_USD_PER_M)
    if args.rates:
        rates.update(json.loads(args.rates))

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) if args.out else SPIKES / "runs" / f"{stamp}-{args.browser}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"run dir: {out_dir}")

    rep_wav, rep_timeline = synthesize_rep_wav(out_dir, args.voice)
    rep_total = rep_timeline[-1]["end"] + GAP_SECONDS
    print(f"rep audio: {rep_total:.1f}s across {len(rep_timeline)} lines")

    server, url = serve_spikes()
    launch_kwargs: dict = {"headless": not args.headed}
    if args.browser != "chromium":
        launch_kwargs["channel"] = args.browser
    launch_kwargs["args"] = [
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
        f"--use-file-for-fake-audio-capture={rep_wav}%noloop",
        "--autoplay-policy=no-user-gesture-required",
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context()
        context.grant_permissions(["microphone"])
        context.add_init_script(INIT_SCRIPT)
        page = context.new_page()
        page.goto(url)
        page.evaluate(HOOK_SCRIPT)
        page.fill("#endpoint", endpoint)
        page.fill("#apiKey", api_key)
        page.fill("#model", model)
        t_connect = time.time()
        page.click("#btnConnect")
        page.wait_for_function(
            "() => document.getElementById('status').textContent.startsWith('Connected')"
            " || document.getElementById('status').textContent.startsWith('Failed')",
            timeout=45_000,
        )
        status = page.text_content("#status")
        print(f"status after connect: {status} ({time.time() - t_connect:.1f}s)")
        if status.startswith("Failed"):
            (out_dir / "page.log").write_text(page.text_content("#log"), encoding="utf-8")
            browser.close()
            server.shutdown()
            return 1

        dropped_at_turn = None
        dropped_at = None
        post_drop_state = None
        deadline = time.time() + min(args.max_seconds, rep_total + 25)
        while time.time() < deadline:
            turns = page.evaluate("() => turns.length")
            if dropped_at_turn is None and turns >= args.drop_after:
                page.evaluate("() => { window.__push('ws.dropped'); dropWs(); }")
                dropped_at_turn, dropped_at = turns, time.time()
                print(f"signalling WS dropped after turn {turns}")
            if dropped_at and post_drop_state is None and time.time() - dropped_at > 8:
                post_drop_state = page.evaluate(
                    "() => ({pc: pc && pc.connectionState, ice: pc && pc.iceConnectionState,"
                    " remote_track: pc && pc.getReceivers()[0] ? pc.getReceivers()[0].track.readyState : null,"
                    " stream_active: audioEl && audioEl.srcObject ? audioEl.srcObject.active : null})"
                )
                print(f"peer connection 8 s after drop: {post_drop_state}")
            time.sleep(0.5)
        turns_total = page.evaluate("() => turns.length")
        harness_latencies = page.evaluate("() => turns.slice()")
        page.evaluate("() => disconnect()")
        time.sleep(1.0)
        rec = page.evaluate(READ_RECORDING)
        events = page.evaluate("() => window.__ev")
        page_log = page.text_content("#log")
        browser_version = browser.version
        browser.close()
    server.shutdown()

    (out_dir / "page.log").write_text(page_log, encoding="utf-8")
    (out_dir / "events.json").write_text(json.dumps(events, indent=1), encoding="utf-8")

    # --- audio truth
    audio = {"recorded": bool(rec)}
    if rec:
        ext = "m4a" if "mp4" in rec["type"] else "webm"
        webm = out_dir / f"recording.{ext}"
        webm.write_bytes(base64.b64decode(rec["b64"]))
        audio.update({"file": webm.name, "bytes": rec["size"], "mime": rec["type"]})
        windows = rec.get("rms") or []
        audio["duration_s"] = round(rec["duration"], 2) if rec.get("duration") else None
        audio["decode_error"] = rec.get("decodeError")

        rec_start = next((e["t"] for e in events if e["type"] == "recorder.start"), None)
        if rec_start is not None and windows:
            def rel(t: float) -> float:
                return (t - rec_start) / 1000.0
            rep_spans, buyer_spans = [], []
            open_rep = None
            open_buyer = None
            for e in events:
                if e["type"] == "input_audio_buffer.speech_started":
                    open_rep = rel(e["t"])
                elif e["type"] == "input_audio_buffer.speech_stopped" and open_rep is not None:
                    rep_spans.append((open_rep, rel(e["t"])))
                    open_rep = None
                elif e["type"] == "remote.audio.onset":
                    open_buyer = rel(e["t"])
                elif e["type"] == "remote.audio.end" and open_buyer is not None:
                    if rel(e["t"]) - open_buyer > 0.3:
                        buyer_spans.append((open_buyer, rel(e["t"])))
                    open_buyer = None
            busy = rep_spans + buyer_spans
            quiet = []
            cursor = 0.0
            for s, e_ in sorted(busy):
                if s - cursor > 0.5:
                    quiet.append((cursor, s))
                cursor = max(cursor, e_)
            audio.update(
                {
                    "rep_spans": len(rep_spans),
                    "buyer_spans": len(buyer_spans),
                    "rms_rep": round(mean_rms_in(windows, rep_spans), 4),
                    "rms_buyer": round(mean_rms_in(windows, buyer_spans), 4),
                    "rms_quiet": round(mean_rms_in(windows, quiet), 4),
                }
            )
            floor = max(audio["rms_quiet"], 0.002)
            audio["both_voices_present"] = (
                audio["rms_rep"] > 3 * floor and audio["rms_buyer"] > 3 * floor
            )

    # --- control channel
    post_drop_turns = (turns_total - dropped_at_turn) if dropped_at_turn is not None else None
    control = {
        "dropped_after_turn": dropped_at_turn,
        "turns_total": turns_total,
        "turns_after_drop": post_drop_turns,
        "peer_connection_8s_after_drop": post_drop_state,
        "audio_survives_signalling_drop": bool(post_drop_turns),
    }

    # --- latency
    audible = []
    pending = None
    for e in events:
        if e["type"] == "input_audio_buffer.speech_stopped":
            pending = e["t"]
        elif e["type"] == "remote.audio.onset" and pending is not None:
            audible.append(round(e["t"] - pending))
            pending = None
    def p95(xs: list[int]) -> int | None:
        if not xs:
            return None
        xs = sorted(xs)
        return xs[min(len(xs) - 1, math.ceil(0.95 * len(xs)) - 1)]
    latency = {
        "harness_transcript_ms": harness_latencies,
        "harness_mean_ms": round(sum(harness_latencies) / len(harness_latencies)) if harness_latencies else None,
        "audible_ms": audible,
        "audible_mean_ms": round(sum(audible) / len(audible)) if audible else None,
        "audible_p95_ms": p95(audible),
        "budget_ms": 2000,
    }

    # --- cost
    usage = summarize_usage(events)
    cost = price(usage, rates)
    session_seconds = None
    t_first = next((e["t"] for e in events if e["type"] == "recorder.start"), None)
    t_last = max((e["t"] for e in events), default=None)
    if t_first is not None and t_last is not None:
        session_seconds = round((t_last - t_first) / 1000.0, 1)
    cost_truth = {
        "usage_tokens": usage,
        "rates_usd_per_1m": rates,
        "cost": cost,
        "session_seconds": session_seconds,
        "usd_per_minute": round(cost["total_usd"] / (session_seconds / 60), 4) if session_seconds else None,
    }

    transcript = [
        {"who": "rep" if e["type"].startswith("conversation.item") else "buyer", "text": e["transcript"]}
        for e in events
        if e.get("transcript")
    ]
    errors = [e for e in events if e.get("error")]

    report = {
        "run": stamp,
        "browser": args.browser,
        "browser_version": browser_version,
        "model": model,
        "control_channel": control,
        "audio_truth": audio,
        "latency": latency,
        "cost_truth": cost_truth,
        "transcript": transcript,
        "errors": errors,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("control_channel", "audio_truth", "latency")}, indent=2))
    print(json.dumps({"usage_tokens": usage, "cost": cost, "session_seconds": session_seconds,
                      "usd_per_minute": cost_truth["usd_per_minute"]}, indent=2))
    print(f"transcript turns: {len(transcript)}; errors: {len(errors)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
