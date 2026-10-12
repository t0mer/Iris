"""Local OpenAI-compatible multipart transcription adapter."""

import asyncio
from pathlib import Path

import httpx

from app.jobs.queue import TransientError
from app.transcription.base import TranscriptResult, raise_for_status


class WhisperTranscriber:
    name = "whisper.cpp"

    def __init__(
        self,
        url: str,
        api_key: str | None = None,
        model: str = "auto",
        fallback_model: str | None = "ivrit-large-v3",
    ) -> None:
        self.url = url
        self.model = model
        self.fallback_model = fallback_model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(timeout=600, headers=headers)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def transcribe(self, path: Path, mime_type: str) -> TranscriptResult:
        data = await asyncio.to_thread(path.read_bytes)
        try:
            response = await self._client.post(
                self.url,
                data={"response_format": "json", "model": self.model},
                files={"file": (path.name, data, mime_type)},
            )
            if response.status_code == 422 and self.model == "auto" and self.fallback_model:
                response = await self._client.post(
                    self.url,
                    data={"response_format": "json", "model": self.fallback_model},
                    files={"file": (path.name, data, mime_type)},
                )
        except httpx.HTTPError as exc:
            raise TransientError("Local transcription unreachable") from exc
        if response.status_code == 422:
            raise TransientError("whisper.cpp HTTP 422; transcription will be retried")
        raise_for_status("whisper.cpp", response)
        try:
            text = response.json()["text"]
            if not isinstance(text, str):
                raise ValueError("Invalid transcript")
        except (KeyError, TypeError, ValueError) as exc:
            raise TransientError("Local transcription returned invalid output") from exc
        return TranscriptResult(text=text.strip(), language=None, duration_seconds=None)
