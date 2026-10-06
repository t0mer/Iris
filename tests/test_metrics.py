from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.classify.moderation import URL as MOD_URL
from app.metrics import REGISTRY
from app.transcription import openai as openai_t
from tests.test_alerts import SEND_URL, msg_body, run_all, setup
from tests.test_media_pipeline import MEDIA_URL, serve
from tests.test_webhooks import fx, make_instance, post
from tests.test_worker import mod_response


def val(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_metrics_endpoint_is_unauthenticated_and_exposes_all_families(
    app_client: Any,
) -> None:
    app_client.cookies.clear()
    r = await app_client.get("/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    for family in (
        "iris_webhooks_total",
        "iris_messages_processed_total",
        "iris_stage_duration_seconds",
        "iris_provider_requests_total",
        "iris_provider_duration_seconds",
        "iris_transcription_seconds_audio_total",
        "iris_alerts_total",
    ):
        assert f"# TYPE {family}" in r.text, family
    assert 'iris_jobs{status="queued"}' in r.text


async def test_webhook_results_are_counted(app_client: Any) -> None:
    iid, token = await make_instance(app_client)
    inst = str(iid)
    before = {
        r: val("iris_webhooks_total", instance=inst, result=r)
        for r in ("accepted", "duplicate", "skipped", "rejected")
    }
    unknown = val("iris_webhooks_total", instance="unknown", result="rejected")
    await post(app_client, token, fx("text_received_mixed"))
    await post(app_client, token, fx("text_received_mixed"))  # duplicate
    await post(app_client, token, fx("message_reaction"))  # ignored event
    await post(app_client, token, b"not json")  # rejected
    await post(app_client, "no-such-token", fx("text_received_mixed"))
    after = {r: val("iris_webhooks_total", instance=inst, result=r) for r in before}
    assert {r: after[r] - before[r] for r in before} == {
        "accepted": 1,
        "duplicate": 1,
        "skipped": 1,
        "rejected": 1,
    }
    assert val("iris_webhooks_total", instance="unknown", result="rejected") == unknown + 1


@respx.mock
async def test_pipeline_provider_and_alert_metrics(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    processed = val("iris_messages_processed_total", type="text", verdict="harmful")
    stage_n = val("iris_stage_duration_seconds_count", stage="moderation")
    mod_ok = val(
        "iris_provider_requests_total", provider="openai", endpoint="moderations", status="200"
    )
    send_ok = val(
        "iris_provider_requests_total", provider="openwa", endpoint="send-text", status="201"
    )
    sent = val("iris_alerts_total", category="violence", delivery_status="sent")
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    assert val("iris_messages_processed_total", type="text", verdict="harmful") == processed + 1
    assert val("iris_stage_duration_seconds_count", stage="moderation") == stage_n + 1
    assert (
        val("iris_provider_requests_total", provider="openai", endpoint="moderations", status="200")
        == mod_ok + 1
    )
    assert (
        val("iris_provider_requests_total", provider="openwa", endpoint="send-text", status="201")
        == send_ok + 1
    )
    assert val("iris_alerts_total", category="violence", delivery_status="sent") == sent + 1
    assert (
        val("iris_provider_duration_seconds_count", provider="openai", endpoint="moderations") > 0
    )
    text = (await app_client.get("/metrics")).text
    assert 'iris_jobs{status="done"}' in text
    await deps.providers.aclose()


@respx.mock
async def test_transcribed_audio_seconds_and_failed_provider_status(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    serve("voice.ogg")
    respx.post(openai_t.URL).mock(return_value=httpx.Response(200, json={"text": "hi there"}))
    respx.post(MOD_URL).mock(return_value=httpx.Response(429))
    secs = val("iris_transcription_seconds_audio_total", provider="openai")
    rate_limited = val(
        "iris_provider_requests_total", provider="openai", endpoint="moderations", status="429"
    )
    await post(app_client, token, msg_body("voice_sent", "VX01", ""))
    await run_all(deps)
    assert val("iris_transcription_seconds_audio_total", provider="openai") > secs  # ~1 s of audio
    assert (
        val("iris_provider_requests_total", provider="openai", endpoint="moderations", status="429")
        == rate_limited + 1
    )
    assert (
        val("iris_provider_requests_total", provider="openwa", endpoint="media", status="200") > 0
    )
    await deps.providers.aclose()
    assert MEDIA_URL and Path


async def test_metrics_token_is_enforced_when_configured(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    app_client.cookies.clear()
    monkeypatch.setenv("IRIS_METRICS_TOKEN", "scrape-secret")
    get_settings.cache_clear()
    assert (await app_client.get("/metrics")).status_code == 401
    bad = await app_client.get("/metrics", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401 and bad.headers["www-authenticate"] == "Bearer"
    ok = await app_client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"})
    assert ok.status_code == 200 and "iris_webhooks_total" in ok.text
    monkeypatch.delenv("IRIS_METRICS_TOKEN")
    get_settings.cache_clear()
    assert (await app_client.get("/metrics")).status_code == 200  # open again when unset


async def test_job_gauge_is_cached_between_scrapes(app_client: Any) -> None:
    from app import metrics

    metrics._gauge_refreshed = 0.0
    _, token = await make_instance(app_client)
    await app_client.get("/metrics")  # refreshes the gauge
    await post(app_client, token, fx("text_received_mixed"))  # a new queued job
    cached = (await app_client.get("/metrics")).text
    assert 'iris_jobs{status="queued"} 0.0' in cached  # served from the cache, no DB hit
    metrics._gauge_refreshed = 0.0
    assert 'iris_jobs{status="queued"} 1.0' in (await app_client.get("/metrics")).text
