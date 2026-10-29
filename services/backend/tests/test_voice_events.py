"""Wire-format mapping and usage aggregation for the brokered call (D29)."""
from app.adapters.voice.azure_voice_live import map_event, session_config
from app.adapters.voice.stub import SCRIPT, StubVoiceProvider
from app.modules.practice.live import add_usage, bound_client_usage, empty_usage


def test_provider_events_map_to_domain_events() -> None:
    assert map_event({"type": "input_audio_buffer.speech_started", "item_id": "i1"}, 10).kind == "rep_started"
    rep = map_event({"type": "conversation.item.input_audio_transcription.completed",
                     "item_id": "i1", "transcript": " Hello there "}, 20)
    assert (rep.kind, rep.item_id, rep.text) == ("rep_transcript", "i1", "Hello there")
    assert map_event({"type": "response.output_item.added", "item": {"id": "b1"}}, 30).item_id == "b1"
    buyer = map_event({"type": "response.audio_transcript.done", "item_id": "b1", "transcript": "Mm."}, 40)
    assert buyer.kind == "buyer_transcript" and buyer.at_ms == 40
    assert map_event({"type": "response.done", "response": {"usage": {"input_tokens": 5}}}, 50).kind == "usage"
    assert map_event({"type": "response.done", "response": {}}, 50) is None
    assert map_event({"type": "session.updated"}, 60) is None


def test_session_config_pins_transcription_and_voice_type() -> None:
    cfg = session_config("Be Priya.", "en-IN-NeerjaNeural", "gpt-realtime")
    assert cfg["input_audio_transcription"]["model"] == "whisper-1"
    assert cfg["voice"] == {"type": "azure-standard", "name": "en-IN-NeerjaNeural"}
    assert session_config("x", "diya", "azure-realtime")["voice"]["type"] == "azure-realtime-native"


def test_usage_buckets_separate_cached_tokens() -> None:
    totals = empty_usage()
    add_usage(totals, {"input_token_details": {"text_tokens": 700, "audio_tokens": 215,
                                               "cached_tokens_details": {"text_tokens": 640, "audio_tokens": 128}},
                       "output_token_details": {"text_tokens": 7, "audio_tokens": 42}})
    assert totals == {"text_in": 60, "text_in_cached": 640, "audio_in": 87, "audio_in_cached": 128,
                      "text_out": 7, "audio_out": 42, "responses": 1}


async def test_stub_call_emits_the_whole_script_then_waits_for_hangup() -> None:
    call = await StubVoiceProvider(gap_seconds=0).open_call(sdp_offer=None, instructions="", voice="", user_ref="u")
    assert call.session.mode == "stub" and call.session.sdp_answer is None
    seen = []
    async for event in call.events():
        seen.append(event)
        if sum(e.kind.endswith("transcript") for e in seen) == len(SCRIPT):
            await call.close()
    assert sum(e.kind == "rep_transcript" for e in seen) == sum(s == "rep" for s, _ in SCRIPT)
    assert all(a.at_ms <= b.at_ms for a, b in zip(seen, seen[1:], strict=False))


def test_browser_reported_usage_is_capped_by_call_length() -> None:
    """D32: usage arrives from the browser, so it is bounded by physics, not trusted."""
    honest = bound_client_usage({"audio_in": 1500, "audio_out": 1200, "text_in": 900, "responses": 20}, 170_000)
    assert honest["audio_in"] == 1500 and honest["responses"] == 20
    inflated = bound_client_usage({"audio_in": 10**7, "text_out": 10**7, "responses": 10**6}, 60_000)
    assert inflated["audio_in"] == 60 * 40 and inflated["responses"] == 60
    assert inflated["text_out"] == 60 * 20_000
    assert bound_client_usage({"audio_in": -5}, 0)["audio_in"] == 0
