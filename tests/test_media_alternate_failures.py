from pathlib import Path

import httpx
import pytest

from app.db.models import Message
from app.jobs.queue import TransientError
from app.media.fetch import fetch_original
from app.openwa.client import OpenWAClient


@pytest.mark.parametrize("primary_status", [502, None])
async def test_primary_failure_does_not_hide_saved_alternate(
    monkeypatch, tmp_path: Path, primary_status
):
    closed = []

    async def connect(db, ref, key):
        def serve(request):
            if ref["instance_id"] == 1:
                if primary_status is None:
                    raise httpx.ReadTimeout("private upstream diagnostic")
                return httpx.Response(primary_status)
            return httpx.Response(
                200, content=b"saved receiver copy", headers={"content-type": "image/webp"}
            )

        client = OpenWAClient("https://wa.invalid", "unused", httpx.MockTransport(serve))
        close = client.aclose

        async def tracked_close():
            closed.append(ref["instance_id"])
            await close()

        client.aclose = tracked_close
        return client, str(ref["instance_id"])

    monkeypatch.setattr("app.media.fetch.openwa_for", connect)
    message = Message(
        type="sticker",
        media={
            "instance_id": 1,
            "chat_id": "chat",
            "message_ref": "target",
            "alternates": [{"instance_id": 2, "chat_id": "chat", "message_ref": "target"}],
        },
    )
    output = tmp_path / "media"
    assert await fetch_original(None, message, b"", output) == "image/webp"
    assert output.read_bytes() == b"saved receiver copy" and closed == [1, 2]


async def test_transient_primary_and_missing_alternate_remain_retryable(monkeypatch, tmp_path):
    async def connect(db, ref, key):
        return OpenWAClient(
            "https://wa.invalid",
            "unused",
            httpx.MockTransport(
                lambda request: httpx.Response(502 if ref["instance_id"] == 1 else 404)
            ),
        ), str(ref["instance_id"])

    monkeypatch.setattr("app.media.fetch.openwa_for", connect)
    message = Message(
        type="image",
        media={
            "instance_id": 1,
            "chat_id": "chat",
            "message_ref": "target",
            "alternates": [{"instance_id": 2, "chat_id": "chat", "message_ref": "target"}],
        },
    )
    with pytest.raises(TransientError):
        await fetch_original(None, message, b"", tmp_path / "media")
