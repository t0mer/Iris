import json
from pathlib import Path

import httpx
import pytest

from app import MAX_BODY, create_app, parse_result


@pytest.fixture
def config(tmp_path):
    return {
        "data_dir": str(tmp_path / "runtime"),
        "engine": "/not/installed",
        "models_dir": str(tmp_path / "models"),
        "api_key": "x" * 64,
        "ffmpeg": "/not/installed",
        "ffprobe": "/not/installed",
    }


@pytest.mark.asyncio
async def test_authentication_precedes_upload(config):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(config)), base_url="http://test"
    ) as client:
        response = await client.post("/v1/audio/transcriptions", content=b"not audio")
        assert response.status_code == 401
        assert client.headers.get("Authorization") is None


@pytest.mark.asyncio
async def test_health_reports_missing_models(config):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(config)), base_url="http://test"
    ) as client:
        response = await client.get("/healthz")
        assert response.status_code == 503


@pytest.mark.asyncio
async def test_unknown_model_and_fake_audio_are_rejected(config):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(config)),
        base_url="http://test",
        headers={"Authorization": "Bearer " + config["api_key"]},
    ) as client:
        response = await client.post(
            "/inference",
            data={"model": "../../etc/passwd"},
            files={"file": ("sample.wav", b"fake", "audio/wav")},
        )
        assert response.status_code == 400
        response = await client.post(
            "/inference", files={"file": ("sample.wav", b"fake", "audio/wav")}
        )
        assert response.status_code == 415
        assert list((Path(config["data_dir"]) / "tmp").iterdir()) == []


@pytest.mark.asyncio
async def test_body_size_is_bounded(config):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(config)),
        base_url="http://test",
        headers={"Authorization": "Bearer " + config["api_key"]},
    ) as client:
        response = await client.post("/inference", content=b"x" * (MAX_BODY + 1))
        assert response.status_code == 413


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"result": {"language": "he"}, "transcription": []},
        {"result": {"language": "he"}, "transcription": [{"text": 123}]},
    ],
)
def test_failed_or_empty_backend_result_is_not_a_transcript(result):
    with pytest.raises(ValueError):
        parse_result(result)


def test_unicode_transcript_preserved():
    result = {"result": {"language": "he"}, "transcription": [{"text": " שלום עולם "}]}
    assert parse_result(json.loads(json.dumps(result)))[0] == "שלום עולם"
