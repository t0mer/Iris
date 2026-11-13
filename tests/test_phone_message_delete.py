from typing import Any

from tests.test_messages_api import seed


async def test_phone_delete_retains_messages_by_default(app_client: Any) -> None:
    ids = await seed(app_client)
    assert (await app_client.delete(f"/api/instances/{ids['i1']}")).status_code == 204
    assert (await app_client.get("/api/messages")).json()["total"] == 4


async def test_opt_in_deletes_only_exclusive_messages(app_client: Any) -> None:
    ids = await seed(app_client)
    assert (
        await app_client.delete(f"/api/instances/{ids['i1']}?delete_messages=true")
    ).status_code == 204
    remaining = (await app_client.get("/api/messages")).json()
    assert remaining["total"] == 3
    received = [m for m in remaining["items"] if not m["from_me"]]
    assert len(received) == 1
    assert [kid["id"] for kid in received[0]["kids"]] == [ids["i2"]]


async def test_sender_cannot_delete_saved_messages(app_client: Any) -> None:
    ids = await seed(app_client)
    await app_client.put(
        "/api/settings", json={"settings": {"alerts.sender_instance_id": ids["i1"]}}
    )
    assert (
        await app_client.delete(f"/api/instances/{ids['i1']}?delete_messages=true")
    ).status_code == 422
    assert (await app_client.get("/api/messages")).json()["total"] == 4
