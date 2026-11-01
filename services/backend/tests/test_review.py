"""D43: naming diarized speakers, reading Azure's reply, and the upload's consent rule."""
import pytest

from app.adapters.transcription import AzureTranscriber, Phrase, parse_azure
from app.errors import AppError
from app.modules.review import service as review


def _phrases(*speakers: int) -> list[Phrase]:
    return [Phrase(s, f"line {i}", i * 100, i * 100 + 90) for i, s in enumerate(speakers)]


def test_the_uploader_names_who_spoke_first() -> None:
    assert [t[0] for t in review.to_turns(_phrases(1, 2), rep_speaks_first=True)] == ["rep", "buyer"]
    assert [t[0] for t in review.to_turns(_phrases(1, 2), rep_speaks_first=False)] == ["buyer", "rep"]


def test_a_run_of_one_speaker_is_one_turn() -> None:
    turns = review.to_turns(_phrases(1, 1, 2), rep_speaks_first=True)
    assert turns == [("rep", "line 0 line 1", 0, 190), ("buyer", "line 2", 200, 290)]


def test_a_call_with_one_voice_is_refused() -> None:
    with pytest.raises(review.OneSpeakerOnly):
        review.to_turns(_phrases(1, 1), rep_speaks_first=True)


def test_azure_reply_is_ordered_and_timed() -> None:
    transcript = parse_azure({"durationMilliseconds": 900, "phrases": [
        {"speaker": 2, "offsetMilliseconds": 500, "durationMilliseconds": 100, "text": "second"},
        {"speaker": 1, "offsetMilliseconds": 10, "durationMilliseconds": 200, "text": "first"},
        {"speaker": 1, "offsetMilliseconds": 700, "durationMilliseconds": 10, "text": ""}]})
    assert [(p.speaker, p.text, p.start_ms, p.end_ms) for p in transcript.phrases] == [
        (1, "first", 10, 210), (2, "second", 500, 600)]
    assert transcript.duration_ms == 900


@pytest.mark.parametrize("endpoint", ["https://x.services.ai.azure.com/", "x.services.ai.azure.com"])
def test_the_endpoint_may_come_with_or_without_a_scheme(endpoint: str) -> None:
    assert AzureTranscriber(endpoint, "k")._url.startswith(
        "https://x.services.ai.azure.com/speechtotext/transcriptions:transcribe")


async def test_no_consent_no_upload() -> None:
    with pytest.raises(AppError) as err:
        await review.create_review(None, None, None, rep_speaks_first=True, consent=False)
    assert err.value.code == "consent_required"
