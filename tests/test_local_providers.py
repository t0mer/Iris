import json

import httpx
import pytest
import respx

from app.classify.ollama import OllamaModerator
from app.classify.thresholds import DEFAULT_THRESHOLDS
from app.jobs.queue import PermanentError, TransientError
from app.transcription.whisper import WhisperTranscriber


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"violence": 0},
        {k: True for k in DEFAULT_THRESHOLDS},
        {k: 2 for k in DEFAULT_THRESHOLDS},
    ],
)
@respx.mock
async def test_invalid_local_scores_never_become_safe(bad):
    respx.post("http://ollama/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": json.dumps(bad)}})
    )
    client = OllamaModerator("http://ollama", "model")
    try:
        with pytest.raises(TransientError):
            await client.moderate("", "test")
    finally:
        await client.aclose()


async def test_invalid_images_are_not_marked_safe():
    client = OllamaModerator("http://ollama", "model")
    try:
        with pytest.raises(PermanentError):
            await client.moderate("", [{"type": "image_url"}])
    finally:
        await client.aclose()


@respx.mock
async def test_local_vision_sends_image_and_caption_and_validates_capability():
    import base64

    encoded = base64.b64encode(b"jpeg test bytes").decode()
    metadata = respx.post("http://ollama/api/show").mock(
        return_value=httpx.Response(200, json={"capabilities": ["completion", "vision"]})
    )
    route = respx.post("http://ollama/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"content": json.dumps(dict.fromkeys(DEFAULT_THRESHOLDS, 0))}}
        )
    )
    client = OllamaModerator("http://ollama", "vision-model")
    payload = [
        {"type": "text", "text": "caption"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + encoded}},
    ]
    try:
        result = await client.moderate("", payload)
        assert result.model == "vision-model"
        message = json.loads(route.calls[0].request.content)["messages"][1]
        assert message == {"role": "user", "content": "caption", "images": [encoded]}
        metadata.mock(return_value=httpx.Response(200, json={"capabilities": ["completion"]}))
        with pytest.raises(PermanentError, match="does not support images"):
            await client.moderate("", payload)
        assert len(route.calls) == 1
    finally:
        await client.aclose()


@respx.mock
async def test_local_transcription_auth_model_and_invalid_output(tmp_path):
    path = tmp_path / "sample.mp3"
    path.write_bytes(b"test audio")
    route = respx.post("http://mac/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": None})
    )
    client = WhisperTranscriber("http://mac/v1/audio/transcriptions", "test-token", "auto")
    try:
        with pytest.raises(TransientError):
            await client.transcribe(path, "audio/mpeg")
        request = route.calls[0].request
        assert request.headers["Authorization"] == "Bearer test-token"
        assert b"auto" in request.content
    finally:
        await client.aclose()


@respx.mock
async def test_auto_rejection_retries_local_hebrew_model_once(tmp_path):
    path = tmp_path / "sample.wav"
    path.write_bytes(b"audio")
    route = respx.post("http://mac/v1/audio/transcriptions").mock(
        side_effect=[
            httpx.Response(422, json={"detail": "Local transcription failed"}),
            httpx.Response(200, json={"text": "תודה רבה"}),
        ]
    )
    client = WhisperTranscriber("http://mac/v1/audio/transcriptions")
    try:
        result = await client.transcribe(path, "audio/wav")
        assert result.text == "תודה רבה"
        assert len(route.calls) == 2
        assert b"ivrit-large-v3" in route.calls[1].request.content
    finally:
        await client.aclose()


@respx.mock
async def test_local_memory_failure_is_retryable_without_hebrew_fallback(tmp_path):
    path = tmp_path / "sample.wav"
    path.write_bytes(b"audio")
    route = respx.post("http://mac/v1/audio/transcriptions").mock(
        return_value=httpx.Response(503, headers={"Retry-After": "60"})
    )
    client = WhisperTranscriber("http://mac/v1/audio/transcriptions")
    try:
        with pytest.raises(TransientError) as error:
            await client.transcribe(path, "audio/wav")
        assert error.value.retry_after == 60
        assert len(route.calls) == 1
    finally:
        await client.aclose()


@respx.mock
async def test_422_after_fallback_is_retryable(tmp_path):
    path = tmp_path / "sample.wav"
    path.write_bytes(b"audio")
    route = respx.post("http://mac/v1/audio/transcriptions").mock(return_value=httpx.Response(422))
    client = WhisperTranscriber("http://mac/v1/audio/transcriptions")
    try:
        with pytest.raises(TransientError, match="422"):
            await client.transcribe(path, "audio/wav")
        assert len(route.calls) == 2
    finally:
        await client.aclose()
