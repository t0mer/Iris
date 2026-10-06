import json
from pathlib import Path
from typing import Any

import pytest

from app.openwa.payloads import PayloadError, message_hash, parse_change, parse_event

FIX = Path(__file__).parent / "fixtures" / "openwa"
NAMES = [p.stem for p in sorted(FIX.glob("*.json"))]
EVENTS = {"message_edited", "message_revoked", "message_reaction"}


def load(name: str) -> dict[str, Any]:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_fixtures_present() -> None:
    assert len(NAMES) >= 15


@pytest.mark.parametrize("name", sorted(EVENTS))
def test_non_message_events_ignored(name: str) -> None:
    assert parse_event(load(name)) is None


def test_text_sent_is_from_me_without_sender_name() -> None:
    m = parse_event(load("text_sent_he"))
    assert m and m.type == "text" and m.from_me and m.sender_name is None
    assert m.text == "שלום! זו הודעת בדיקה של Iris" and not m.is_group
    assert m.wa_message_id == "3EB0206F7B189DBEBC16C8"


def test_received_mixed_text_and_sender_name() -> None:
    m = parse_event(load("text_received_mixed"))
    assert m and not m.from_me and m.sender_name and m.text and "mixed" in m.text


@pytest.mark.parametrize(
    ("name", "type_", "mime"),
    [
        ("image_caption_sent", "image", "image/jpeg"),
        ("image_nocaption_received", "image", "image/jpeg"),
        ("voice_sent", "voice", "audio/ogg; codecs=opus"),
        ("audio_received", "audio", "audio/mpeg"),
        ("video_sent", "video", "video/mp4"),
        ("sticker_received", "sticker", "image/webp"),
        ("document_sent", "document", "text/plain"),
    ],
)
def test_media_types(name: str, type_: str, mime: str) -> None:
    m = parse_event(load(name))
    assert m and m.type == type_ and m.media and m.media.mimetype == mime


def test_caption_vs_no_caption() -> None:
    assert parse_event(load("image_caption_sent")).text == "תמונה עם כיתוב"  # type: ignore[union-attr]
    assert parse_event(load("image_nocaption_received")).text is None  # type: ignore[union-attr]


def test_omitted_media_has_no_inline_data_but_small_document_does() -> None:
    img = parse_event(load("image_caption_sent"))
    doc = parse_event(load("document_sent"))
    assert img and img.media and img.media.inline_base64 is None and img.media.size_bytes
    assert doc and doc.media and doc.media.inline_base64 and doc.media.filename == "doc.txt"


def test_quoted_reply_links_original_hash() -> None:
    m = parse_event(load("reply_received"))
    assert m and m.quoted_wa_message_id == "3EB09809BE1A0882DA5F4E"


def test_group_message_uses_author_and_group_chat() -> None:
    m = parse_event(load("group_text_received"))
    assert m and m.is_group and m.wa_chat_id.endswith("@g.us")
    assert m.sender_wa_id == "333333333333333@lid" and m.sender_name == "Group Member"
    assert m.wa_message_id == "3A3C2592D2A166446132"


def test_unknown_type_maps_to_other() -> None:
    m = parse_event(load("unknown_received"))
    assert m and m.type == "other" and m.text is None


def test_same_message_same_hash_for_sender_and_receiver_views() -> None:
    assert message_hash("true_1@lid_ABC123") == message_hash("false_2@lid_ABC123") == "ABC123"


def test_malformed_message_event_raises() -> None:
    with pytest.raises(PayloadError):
        parse_event({"event": "message.received", "data": {"id": "x"}})


def test_status_broadcast_skipped() -> None:
    body = load("text_received_mixed")
    body["data"]["isStatusBroadcast"] = True
    assert parse_event(body) is None


def test_edit_carries_the_new_text_and_the_hash_of_the_original() -> None:
    raw = load("message_edited")
    c = parse_change(raw)
    assert c and c.kind == "edited" and c.new_text
    assert c.wa_message_id == message_hash(raw["data"]["messageId"])


def test_revoke_points_at_the_original_not_the_revoke_stub() -> None:
    raw = load("message_revoked")
    c = parse_change(raw)
    assert c and c.kind == "revoked" and c.new_text is None
    assert c.wa_message_id == message_hash(raw["data"]["revokedId"])
    assert c.wa_message_id != message_hash(raw["data"]["id"])


@pytest.mark.parametrize("name", ["text_sent_he", "message_reaction"])
def test_other_events_are_not_changes(name: str) -> None:
    assert parse_change(load(name)) is None


def test_change_without_an_id_is_rejected() -> None:
    with pytest.raises(PayloadError):
        parse_change({"event": "message.revoked", "data": {"id": "true_x_y"}})
