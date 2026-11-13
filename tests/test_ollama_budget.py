"""Never accept truncated structured output or silently overfill local context."""

import json

import pytest
import respx

from app.classify.ollama import MAX_CONTEXT_TOKENS, OllamaModerator, inference_options
from app.classify.thresholds import DEFAULT_THRESHOLDS
from app.jobs.queue import PermanentError, TransientError


def test_visual_context_reserves_room_for_complete_scores():
    options = inference_options([{"content": "caption"}], 1)
    assert options["num_ctx"] >= 8192
    assert options["num_predict"] == 1024
    assert options["presence_penalty"] == 0 and options["repeat_penalty"] == 1
    video = inference_options([{"content": "caption"}], 6)
    assert 6 * 4096 + 1024 < video["num_ctx"] <= MAX_CONTEXT_TOKENS


def test_oversized_input_is_rejected_without_truncating_target():
    with pytest.raises(PermanentError, match="context budget"):
        inference_options([{"content": "א" * MAX_CONTEXT_TOKENS}], 0)


def test_configured_budget_caps_context_and_reserves_configured_output():
    options = inference_options([{"content": "x" * 7000}], 0, 10000, 2048)
    assert options["num_ctx"] == 10000
    assert options["num_predict"] == 2048
    with pytest.raises(PermanentError, match="context budget"):
        inference_options([{"content": "x" * 7000}], 1, 10000, 2048)


async def test_provider_settings_validate_persist_and_rebuild_client(app_client):
    from app.classify.evaluation_state import configuration_fingerprint
    from app.providers import Providers

    providers = Providers()
    async with app_client.app.state.session_factory() as db:
        before = await configuration_fingerprint(db)
    values = {
        "runtime.classification_provider": "ollama",
        "runtime.ollama_context_tokens": 16384,
        "runtime.ollama_output_tokens": 2048,
    }
    assert (await app_client.put("/api/settings", json={"settings": values})).status_code == 200
    saved = (await app_client.get("/api/settings")).json()
    assert all(saved[k] == v for k, v in values.items())
    try:
        first = providers.moderation("")
        assert first.context_tokens == 16384 and first.output_tokens == 2048
        async with app_client.app.state.session_factory() as db:
            assert await configuration_fingerprint(db) != before
        for bad in (0, True, 8192.5, 65536):
            response = await app_client.put(
                "/api/settings",
                json={
                    "settings": {
                        "runtime.ollama_context_tokens": bad,
                        "runtime.ollama_output_tokens": 1024,
                    }
                },
            )
            assert response.status_code == 422
        assert providers.moderation("") is first
        assert (
            await app_client.put(
                "/api/settings", json={"settings": {"runtime.ollama_output_tokens": 1024}}
            )
        ).status_code == 200
        second = providers.moderation("")
        assert second is not first and second.output_tokens == 1024
    finally:
        await providers.aclose()


@respx.mock
async def test_provider_test_uses_unsaved_budget(app_client):
    route = respx.post("http://ollama/api/chat").respond(
        200, json={"message": {"content": json.dumps(dict.fromkeys(DEFAULT_THRESHOLDS, 0))}}
    )
    response = await app_client.post(
        "/api/settings/test/ollama",
        json={
            "base_url": "http://ollama",
            "model": "local",
            "context_tokens": 8192,
            "output_tokens": 2048,
        },
    )
    assert response.status_code == 200 and response.json()["ok"]
    options = json.loads(route.calls.last.request.content)["options"]
    assert options["num_predict"] == 2048 and options["num_ctx"] == 8192
    assert (
        await app_client.post(
            "/api/settings/test/ollama", json={"base_url": "http://ollama", "context_tokens": True}
        )
    ).status_code == 422


@pytest.mark.parametrize("valid_json", [False, True])
@respx.mock
async def test_length_stop_cannot_be_accepted_even_if_json_looks_safe(valid_json):
    content = json.dumps(dict.fromkeys(DEFAULT_THRESHOLDS, 0)) if valid_json else '{"violence":'
    route = respx.post("http://ollama/api/chat").respond(
        200,
        json={
            "done_reason": "length",
            "message": {"content": content},
        },
    )
    client = OllamaModerator("http://ollama", "local")
    try:
        with pytest.raises(TransientError, match="token/context limit"):
            await client.moderate("local", "target")
        payload = json.loads(route.calls.last.request.content)
        assert payload["options"]["num_ctx"] >= 8192
    finally:
        await client.aclose()


@respx.mock
async def test_complete_structured_output_still_validates_every_category():
    route = respx.post("http://ollama/api/chat")
    client = OllamaModerator("http://ollama", "local")
    try:
        route.respond(
            200,
            json={
                "done_reason": "stop",
                "message": {
                    "content": json.dumps(dict.fromkeys(DEFAULT_THRESHOLDS, 0)),
                },
            },
        )
        assert (await client.moderate("local", "target")).scores["violence"] == 0
        route.respond(
            200,
            json={
                "done_reason": "stop",
                "message": {
                    "content": '{"violence": 0}',
                },
            },
        )
        with pytest.raises(TransientError, match="invalid classification"):
            await client.moderate("local", "target")
    finally:
        await client.aclose()
