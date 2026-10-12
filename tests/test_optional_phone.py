from typing import Any

import pytest

from app.security.two_factor import GREEN_API_KEY
from tests.test_alert_readiness import parent, provider


@pytest.mark.parametrize("empty", [None, "", "   "])
async def test_selected_parent_can_clear_optional_phone(app_client: Any, empty: Any) -> None:
    uid = await parent(app_client, "parent", "+15550100102")
    await provider(app_client, GREEN_API_KEY)
    await app_client.put(
        "/api/settings",
        json={"settings": {"alerts.recipient": "+15550100102", "alerts.channel": "greenapi"}},
    )
    result = await app_client.put(
        f"/api/users/{uid}", json={"username": "parent", "whatsapp_number": empty}
    )
    assert result.status_code == 200, result.text
    assert result.json()["whatsapp_number"] is None
    assert not result.json()["whatsapp_verified"]
    status = (await app_client.get("/api/settings/alert-readiness")).json()
    assert not status["recipients"][0]["eligible"]
    assert "No WhatsApp number" in status["recipients"][0]["reason"]
