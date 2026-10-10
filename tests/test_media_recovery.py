import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.classify.moderation import URL as MOD_URL
from app.openwa.client import MediaTooLarge, OpenWAClient, OpenWAError
from tests.test_media_pipeline import MEDIA, MEDIA_URL, run_all, setup, the_message
from tests.test_webhooks import fx, post
from tests.test_worker import mod_response


@pytest.mark.parametrize(
    "filename,mimetype",
    [("image.png", "image/png"), ("sticker.webp", "image/webp"), ("video_silent.mp4", "video/mp4")],
)
async def test_exact_message_recovery(filename: str, mimetype: str, tmp_path: Path) -> None:
    content = (MEDIA / filename).read_bytes()

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.params == httpx.QueryParams({"limit": 10, "includeMedia": "true"})
        return httpx.Response(
            200,
            json=[
                {"id": "other", "media": {"data": "ignore"}},
                {
                    "id": "target",
                    "media": {"data": base64.b64encode(content).decode(), "mimetype": mimetype},
                },
            ],
        )

    c = OpenWAClient("https://wa.x", "secret", httpx.MockTransport(handle))
    dest = tmp_path / "recovered"
    try:
        assert (
            await c.recover_media("session", "chat", "target", dest, 25 * 1024 * 1024) == mimetype
        )
        assert dest.read_bytes() == content
    finally:
        await c.aclose()


@pytest.mark.parametrize(
    "media",
    [
        {"data": "https://evil.invalid/private", "mimetype": "image/png"},
        {"data": "%%%", "mimetype": "image/png"},
        {"data": "YQ==", "mimetype": "image/png", "omitted": True},
    ],
)
async def test_recovery_rejects_invalid_or_omitted_payload(
    media: dict[str, Any], tmp_path: Path
) -> None:
    c = OpenWAClient(
        "https://wa.x",
        "secret",
        httpx.MockTransport(lambda _: httpx.Response(200, json=[{"id": "target", "media": media}])),
    )
    dest = tmp_path / "recovered"
    try:
        with pytest.raises(OpenWAError):
            await c.recover_media("s", "chat", "target", dest, 100)
        assert not dest.exists()
    finally:
        await c.aclose()


async def test_recovery_enforces_cap_before_writing(tmp_path: Path) -> None:
    c = OpenWAClient(
        "https://wa.x",
        "secret",
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=[
                    {
                        "id": "target",
                        "media": {
                            "data": base64.b64encode(b"a" * 100).decode(),
                            "mimetype": "image/png",
                        },
                    }
                ],
            )
        ),
    )
    try:
        with pytest.raises(MediaTooLarge):
            await c.recover_media("s", "chat", "target", tmp_path / "out", 10)
        assert not (tmp_path / "out").exists()
    finally:
        await c.aclose()


@respx.mock
@pytest.mark.parametrize("failures", [0, 1])
async def test_worker_classifies_recovered_picture(app_client: Any, failures: int) -> None:
    deps, token = await setup(app_client)
    await app_client.put(
        "/api/settings",
        json={"settings": {"media.recovery_wait_seconds": 0, "media.recovery_attempts": 2}},
    )
    respx.get(url__regex=MEDIA_URL).mock(return_value=httpx.Response(404))
    message_id = json.loads(fx("image_nocaption_received"))["data"]["id"]
    history = respx.get(url__regex=r"https://wa\.x/api/sessions/s/messages/.*/history").mock(
        side_effect=[httpx.Response(503)] * failures
        + [
            httpx.Response(
                200,
                json=[
                    {
                        "id": message_id,
                        "media": {
                            "data": base64.b64encode((MEDIA / "image.png").read_bytes()).decode(),
                            "mimetype": "image/png",
                        },
                    }
                ],
            )
        ]
    )
    respx.post(MOD_URL).mock(return_value=mod_response())
    await post(app_client, token, fx("image_nocaption_received"))
    assert await run_all(deps) == ["done"]
    message, _ = await the_message(app_client)
    assert message.verdict == "safe" and history.call_count == failures + 1
