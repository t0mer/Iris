import json
from typing import Any

import httpx
import pytest
import respx
from loguru import logger
from sqlalchemy import func, select

from app.api import classify
from app.classify.moderation import URL
from app.db.models import Classification, Message

SECRET = "needle-phrase-xyz"


@pytest.fixture(autouse=True)
def _reset_limiter() -> None:
    classify._recent.clear()


def _resp(**scores: float) -> httpx.Response:
    cats = {"violence": 0.0, "harassment": 0.0, **scores}
    return httpx.Response(
        200,
        json={
            "model": "m",
            "results": [{"flagged": False, "categories": {}, "category_scores": cats}],
        },
    )


async def _key(c: Any) -> None:
    await c.put("/api/settings", json={"settings": {"openai.api_key": "sk-secret-key"}})


async def test_requires_auth(app_client: Any) -> None:
    app_client.cookies.clear()
    assert (await app_client.post("/api/classify/test", json={"text": "hi"})).status_code == 401


async def test_no_key(app_client: Any) -> None:
    r = await app_client.post("/api/classify/test", json={"text": "hi"})
    assert r.status_code == 400 and r.json()["detail"] == "No OpenAI API key set"


async def test_scores_bands_and_thresholds(app_client: Any) -> None:
    await _key(app_client)
    with respx.mock:
        respx.post(URL).mock(return_value=_resp(violence=0.9))
        r = await app_client.post("/api/classify/test", json={"text": "hi"})
    j = r.json()
    assert r.status_code == 200 and j["verdict"] == "harmful"
    assert [s["stage"] for s in j["stages"]] == ["moderation"]
    assert j["stages"][0]["high_categories"] == ["violence"]
    assert len(j["thresholds"]) == 13


async def test_saved_thresholds_are_used(app_client: Any) -> None:
    await _key(app_client)
    await app_client.put(
        "/api/settings",
        json={"settings": {"classification.thresholds": {"violence": {"low": 0.95, "high": 0.99}}}},
    )
    with respx.mock:
        respx.post(URL).mock(return_value=_resp(violence=0.9))
        r = await app_client.post("/api/classify/test", json={"text": "hi"})
    assert r.json()["verdict"] == "safe"


async def test_context_refines_unclear_and_is_sent_oldest_first(app_client: Any) -> None:
    await _key(app_client)
    with respx.mock:
        route = respx.post(URL).mock(side_effect=[_resp(violence=0.3), _resp(violence=0.9)])
        r = await app_client.post(
            "/api/classify/test", json={"text": "final", "context": ["first", "second"]}
        )
    j = r.json()
    assert [s["stage"] for s in j["stages"]] == ["moderation", "context"]
    assert j["verdict"] == "harmful"
    sent = json.loads(route.calls[1].request.content)["input"]
    assert sent.index("first") < sent.index("second") < sent.index(">>> Chat: final")


async def test_unclear_without_conclusive_context_is_review(app_client: Any) -> None:
    await _key(app_client)
    with respx.mock:
        respx.post(URL).mock(return_value=_resp(violence=0.3))
        r = await app_client.post("/api/classify/test", json={"text": "x"})
        assert r.json()["verdict"] == "review"
        r = await app_client.post("/api/classify/test", json={"text": "x", "context": ["y"]})
    assert r.json()["verdict"] == "review"


async def test_provider_error_is_502_without_the_key(app_client: Any) -> None:
    await _key(app_client)
    with respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(401))
        r = await app_client.post("/api/classify/test", json={"text": "hi"})
    assert r.status_code == 502 and "sk-secret-key" not in r.text


async def test_input_limits(app_client: Any) -> None:
    for body in (
        {"text": ""},
        {"text": "   "},
        {"text": "x" * 4001},
        {"text": "x", "context": ["y"] * 21},
        {"text": "x", "context": ["y" * 1001]},
    ):
        assert (await app_client.post("/api/classify/test", json=body)).status_code == 422


async def test_provider_outage_is_502(app_client: Any) -> None:
    await _key(app_client)
    with respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(503))
        r = await app_client.post("/api/classify/test", json={"text": "hi"})
    assert r.status_code == 502


async def test_missing_key_does_not_use_up_checks(app_client: Any) -> None:
    for _ in range(classify.MAX_CHECKS + 1):
        assert (await app_client.post("/api/classify/test", json={"text": "a"})).status_code == 400
    assert not classify._recent


async def test_context_check_costs_two_slots(app_client: Any) -> None:
    await _key(app_client)
    with respx.mock:
        respx.post(URL).mock(return_value=_resp())
        for _ in range(classify.MAX_CHECKS // 2):
            body = {"text": "a", "context": ["b"]}
            assert (await app_client.post("/api/classify/test", json=body)).status_code == 200
        r = await app_client.post("/api/classify/test", json={"text": "a", "context": ["b"]})
    assert r.status_code == 429


async def test_rate_limited(app_client: Any) -> None:
    await _key(app_client)
    with respx.mock:
        respx.post(URL).mock(return_value=_resp())
        for _ in range(classify.MAX_CHECKS):
            assert (
                await app_client.post("/api/classify/test", json={"text": "a"})
            ).status_code == 200
        assert (await app_client.post("/api/classify/test", json={"text": "a"})).status_code == 429


async def test_nothing_stored_or_logged(app_client: Any) -> None:
    await _key(app_client)
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")
    try:
        with respx.mock:
            respx.post(URL).mock(return_value=_resp(violence=0.9))
            await app_client.post("/api/classify/test", json={"text": SECRET, "context": [SECRET]})
    finally:
        logger.remove(sink)
    assert SECRET not in "".join(lines)
    async with app_client.app.state.session_factory() as s:
        assert (await s.execute(select(func.count()).select_from(Message))).scalar_one() == 0
        assert (await s.execute(select(func.count()).select_from(Classification))).scalar_one() == 0
