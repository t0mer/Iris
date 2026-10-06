import json
import re
from typing import Any

import pytest
from sqlalchemy import func, select, text

from app.db.models import Alert, Job, Message, MessageRevision
from app.settings_store import set_setting
from tests.test_webhooks import fx, make_instance, post

SENT = "text_sent_he"  # the message_edited fixture edits this one's hash
OLD_TEXT = "שלום! זו הודעת בדיקה של Iris"


def revoke_of(name: str) -> bytes:
    """The revoke fixture, pointed at the message of another fixture (same hash, any chat)."""
    raw = json.loads(fx("message_revoked"))
    original = json.loads(fx(name))["data"]["id"]
    raw["data"]["revokedId"] = original
    return json.dumps(raw).encode()


async def _jobs(c: Any, type_: str) -> list[Job]:
    async with c.app.state.session_factory() as s:
        return list((await s.execute(select(Job).where(Job.type == type_))).scalars())


async def _message(c: Any) -> Message:
    async with c.app.state.session_factory() as s:
        return (await s.execute(select(Message))).scalar_one()


async def _fts(c: Any, q: str) -> int:
    async with c.app.state.session_factory() as s:
        r = await s.execute(
            text("SELECT count(*) FROM messages_fts WHERE messages_fts MATCH :q"), {"q": q}
        )
        return int(r.scalar_one())


async def _alert_for(c: Any, delivery: str) -> int:
    from app.alerts.service import create_alert

    async with c.app.state.session_factory() as s:
        m = (await s.execute(select(Message))).scalar_one()
        a = await create_alert(s, m, {"violence": 0.9})
        a.delivery_status = delivery
        await s.commit()
        return a.id


async def test_edit_keeps_the_original_and_updates_the_text(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx(SENT))
    r = await post(app_client, token, fx("message_edited"))
    assert r.json() == {"result": "edited"}
    new_text = json.loads(fx("message_edited"))["data"]["body"]
    m = await _message(app_client)
    assert m.text == new_text and m.edited_at is not None and m.status == "pending"
    async with app_client.app.state.session_factory() as s:
        revs = list((await s.execute(select(MessageRevision))).scalars())
    assert [(r.message_id, r.text) for r in revs] == [(m.id, OLD_TEXT)]
    assert len(await _jobs(app_client, "process_message")) == 2  # original + the edit


@pytest.mark.sqlite_only
async def test_search_finds_the_new_text_not_the_old(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx(SENT))
    assert await _fts(app_client, "הודעת") == 1
    await post(app_client, token, fx("message_edited"))
    new_word = re.findall(r"\w+", json.loads(fx("message_edited"))["data"]["body"])[0]
    assert await _fts(app_client, "הודעת") == 0 and await _fts(app_client, new_word) == 1


async def test_repeated_and_second_session_edits_are_no_ops(app_client: Any) -> None:
    _, t1 = await make_instance(app_client, "Noa")
    _, t2 = await make_instance(app_client, "Dan")
    await post(app_client, t1, fx(SENT))
    await post(app_client, t1, fx("message_edited"))
    assert (await post(app_client, t1, fx("message_edited"))).json() == {"result": "duplicate"}
    assert (await post(app_client, t2, fx("message_edited"))).json() == {"result": "duplicate"}
    async with app_client.app.state.session_factory() as s:
        n = (await s.execute(select(func.count()).select_from(MessageRevision))).scalar_one()
    assert n == 1


async def test_edit_of_an_unknown_message_is_ignored(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    assert (await post(app_client, token, fx("message_edited"))).json() == {"result": "ignored"}


async def test_two_edits_build_a_history(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx(SENT))
    await post(app_client, token, fx("message_edited"))
    second = json.loads(fx("message_edited"))
    second["data"]["body"] = "third wording"
    await post(app_client, token, json.dumps(second).encode())
    async with app_client.app.state.session_factory() as s:
        texts = [
            r.text
            for r in (
                await s.execute(select(MessageRevision).order_by(MessageRevision.id))
            ).scalars()
        ]
    assert texts == [OLD_TEXT, json.loads(fx("message_edited"))["data"]["body"]]


async def test_revoke_marks_the_message_once_and_keeps_it(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx("text_received_mixed"))
    raw = revoke_of("text_received_mixed")
    assert (await post(app_client, token, raw)).json() == {"result": "revoked"}
    first = (await _message(app_client)).revoked_at
    assert first is not None
    assert (await post(app_client, token, raw)).json() == {"result": "duplicate"}
    m = await _message(app_client)
    assert m.revoked_at == first and m.text  # the content stays for the parent
    assert len(await _jobs(app_client, "process_message")) == 1  # classification not cancelled


async def test_revoke_of_an_unknown_message_is_ignored(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    assert (await post(app_client, token, fx("message_revoked"))).json() == {"result": "ignored"}


async def test_edit_of_a_redacted_message_stores_no_history(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx(SENT))
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message))).scalar_one()
        m.redacted, m.text = True, "[redacted]"
        await s.commit()
    await post(app_client, token, fx("message_edited"))
    m = await _message(app_client)
    assert m.text == "[redacted]" and m.edited_at is not None
    async with app_client.app.state.session_factory() as s:
        assert (
            await s.execute(select(func.count()).select_from(MessageRevision))
        ).scalar_one() == 0


async def test_change_still_needs_the_signature_when_required(app_client: Any) -> None:
    iid, token = await make_instance(app_client)
    async with app_client.app.state.session_factory() as s:
        from app.db.models import Instance

        inst = await s.get(Instance, iid)
        assert inst
        inst.signature_required = True
        await s.commit()
    assert (await post(app_client, token, fx("message_edited"))).status_code == 401


async def test_parent_is_told_only_when_the_alert_was_delivered(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx("text_received_mixed"))
    aid = await _alert_for(app_client, "sent")
    await post(app_client, token, revoke_of("text_received_mixed"))
    jobs = await _jobs(app_client, "notify_change")
    assert [j.payload for j in jobs] == [{"alert_id": aid, "kind": "revoked"}]


async def test_no_follow_up_for_a_suppressed_alert_or_when_switched_off(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx("text_received_mixed"))
    await _alert_for(app_client, "suppressed")
    await post(app_client, token, revoke_of("text_received_mixed"))
    assert await _jobs(app_client, "notify_change") == []

    async with app_client.app.state.session_factory() as s:
        a = (await s.execute(select(Alert))).scalar_one()
        a.delivery_status = "sent"
        await set_setting(s, "alerts.notify_changes", False)
        await s.commit()
    edit = json.loads(fx("text_received_mixed"))["data"]["id"]
    assert edit  # (the revoke above already happened; an edit is a fresh change)
    payload = json.loads(fx("message_edited"))
    payload["data"]["messageId"] = edit
    payload["data"]["body"] = "changed"
    await post(app_client, token, json.dumps(payload).encode())
    assert await _jobs(app_client, "notify_change") == []


async def _classify(c: Any, deps: Any) -> list[str]:
    from tests.test_worker import drain

    return await drain(deps)


async def test_editing_a_harmful_message_into_a_harmless_one_keeps_the_verdict(
    app_client: Any,
) -> None:
    import respx

    from app.classify.moderation import URL
    from tests.test_worker import mod_response, setup

    deps, token = await setup(app_client)
    with respx.mock:
        respx.post(URL).mock(
            side_effect=[mod_response(violence=0.95), mod_response(), mod_response()]
        )
        await post(app_client, token, fx(SENT))
        await _classify(app_client, deps)
        assert (await _message(app_client)).verdict == "harmful"
        await post(app_client, token, fx("message_edited"))
        await _classify(app_client, deps)
    m = await _message(app_client)
    assert m.verdict == "harmful" and m.status == "done" and m.edited_at is not None
    await deps.providers.aclose()


async def test_a_harmless_message_edited_into_a_harmful_one_is_flagged(app_client: Any) -> None:
    import respx

    from app.classify.moderation import URL
    from tests.test_worker import mod_response, setup

    deps, token = await setup(app_client)
    with respx.mock:
        respx.post(URL).mock(side_effect=[mod_response(), mod_response(violence=0.95)])
        await post(app_client, token, fx(SENT))
        await _classify(app_client, deps)
        assert (await _message(app_client)).verdict == "safe"
        await post(app_client, token, fx("message_edited"))
        await _classify(app_client, deps)
    async with app_client.app.state.session_factory() as s:
        assert (await s.execute(select(Alert))).scalar_one().max_score >= 0.9
    assert (await _message(app_client)).verdict == "harmful"
    await deps.providers.aclose()


async def test_redaction_after_an_edit_wipes_the_history(app_client: Any) -> None:
    import respx

    from app.classify.moderation import URL
    from tests.test_worker import mod_response, setup

    deps, token = await setup(app_client)
    with respx.mock:
        respx.post(URL).mock(side_effect=[mod_response(), mod_response(**{"sexual/minors": 0.9})])
        await post(app_client, token, fx(SENT))
        await _classify(app_client, deps)
        await post(app_client, token, fx("message_edited"))
        await _classify(app_client, deps)
    m = await _message(app_client)
    async with app_client.app.state.session_factory() as s:
        n = (await s.execute(select(func.count()).select_from(MessageRevision))).scalar_one()
    assert m.redacted and m.text == "[redacted]" and n == 0
    await deps.providers.aclose()


async def test_api_exposes_flags_and_history_but_not_for_redacted(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx(SENT))
    await post(app_client, token, fx("message_edited"))
    await post(app_client, token, revoke_of(SENT))
    mid = (await _message(app_client)).id
    d = (await app_client.get(f"/api/messages/{mid}")).json()
    assert d["edited_at"] and d["revoked_at"]
    assert [r["text"] for r in d["revisions"]] == [OLD_TEXT]
    listed = (await app_client.get("/api/messages")).json()["items"][0]
    assert listed["edited_at"] and listed["revoked_at"] and "revisions" not in listed

    async with app_client.app.state.session_factory() as s:
        (await s.get(Message, mid)).redacted = True  # type: ignore[union-attr]
        await s.commit()
    d = (await app_client.get(f"/api/messages/{mid}")).json()
    assert d["revisions"] == [] and d["text"] is None


async def test_a_dead_follow_up_does_not_fail_the_delivered_alert(app_client: Any) -> None:
    from app.config import get_settings
    from app.jobs import queue
    from app.jobs.handlers import Deps
    from app.jobs.queue import ClaimedJob
    from app.providers import Providers

    _, token = await make_instance(app_client)
    await post(app_client, token, fx("text_received_mixed"))
    aid = await _alert_for(app_client, "sent")
    deps = Deps(app_client.app.state.session_factory, Providers(), get_settings().key_bytes)
    job = ClaimedJob(99, "notify_change", {"alert_id": aid, "kind": "revoked"}, 5, 5)
    assert await queue.fail(deps.session_factory, job, "boom", transient=True) == "dead"
    async with app_client.app.state.session_factory() as s:
        assert (await s.get(Alert, aid)).delivery_status == "sent"  # type: ignore[union-attr]
    await deps.providers.aclose()


async def test_only_the_later_check_of_a_message_waits(app_client: Any) -> None:
    import pytest
    from sqlalchemy import update

    from app.config import get_settings
    from app.db.models import Job as JobModel
    from app.jobs.handlers import Deps, process_message
    from app.jobs.queue import ClaimedJob, PermanentError, TransientError
    from app.providers import Providers

    _, token = await make_instance(app_client)
    await post(app_client, token, fx(SENT))
    m = await _message(app_client)
    async with app_client.app.state.session_factory() as s:
        s.add(JobModel(type="process_message", payload={"message_id": m.id}))
        await s.commit()
        ids = [j.id for j in (await s.execute(select(JobModel).order_by(JobModel.id))).scalars()]
    deps = Deps(app_client.app.state.session_factory, Providers(), get_settings().key_bytes)
    earlier = ClaimedJob(ids[0], "process_message", {"message_id": m.id}, 1, 5)
    later = ClaimedJob(ids[1], "process_message", {"message_id": m.id}, 1, 5)

    async def mark(job_id: int, status: str) -> None:
        async with app_client.app.state.session_factory() as s:
            await s.execute(update(JobModel).where(JobModel.id == job_id).values(status=status))
            await s.commit()

    await mark(ids[0], "running")
    await mark(ids[1], "running")
    with pytest.raises(TransientError):
        await process_message(later, deps)  # waits for the earlier one
    # The earlier job never waits for the later one; here it fails only for the missing key.
    with pytest.raises(PermanentError, match="OpenAI"):
        await process_message(earlier, deps)
    await deps.providers.aclose()


async def test_follow_up_is_queued_while_the_alert_is_still_pending_and_coalesced(
    app_client: Any,
) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx(SENT))
    aid = await _alert_for(app_client, "pending")
    await post(app_client, token, fx("message_edited"))
    second = json.loads(fx("message_edited"))
    second["data"]["body"] = "yet another wording"
    await post(app_client, token, json.dumps(second).encode())
    jobs = await _jobs(app_client, "notify_change")
    assert [j.payload for j in jobs] == [{"alert_id": aid, "kind": "edited"}]


async def test_follow_up_waits_for_a_pending_alert_and_skips_an_undelivered_one(
    app_client: Any,
) -> None:
    import pytest

    from app.alerts.delivery import notify_change
    from app.config import get_settings
    from app.jobs.handlers import Deps
    from app.jobs.queue import ClaimedJob, TransientError
    from app.providers import Providers

    _, token = await make_instance(app_client)
    await post(app_client, token, fx(SENT))
    aid = await _alert_for(app_client, "pending")
    deps = Deps(app_client.app.state.session_factory, Providers(), get_settings().key_bytes)
    job = ClaimedJob(1, "notify_change", {"alert_id": aid, "kind": "edited"}, 1, 5)
    with pytest.raises(TransientError):
        await notify_change(job, deps)
    async with app_client.app.state.session_factory() as s:
        (await s.get(Alert, aid)).delivery_status = "failed"  # type: ignore[union-attr]
        await s.commit()
    await notify_change(job, deps)  # returns quietly: the parent never got the alert
    await deps.providers.aclose()


async def test_an_older_edit_delivered_late_does_not_roll_the_text_back(
    app_client: Any,
) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx(SENT))
    first = fx("message_edited")
    await post(app_client, token, first)
    newer = json.loads(first)
    newer["data"]["body"] = "newest wording"
    await post(app_client, token, json.dumps(newer).encode())
    assert (await post(app_client, token, first)).json() == {"result": "duplicate"}
    assert (await _message(app_client)).text == "newest wording"


async def test_a_no_op_change_still_records_that_the_phone_is_alive(app_client: Any) -> None:
    from app.db.models import Instance

    iid, token = await make_instance(app_client)
    assert (await post(app_client, token, fx("message_edited"))).json() == {"result": "ignored"}
    async with app_client.app.state.session_factory() as s:
        assert (await s.get(Instance, iid)).last_webhook_at is not None  # type: ignore[union-attr]
