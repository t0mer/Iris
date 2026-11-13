import json
import zipfile
from datetime import UTC, datetime
from xml.sax.saxutils import escape

import pytest
import respx

from app.classify.moderation import URL
from app.db.models import Chat, Message
from app.jobs.queue import PermanentError, enqueue
from app.media import documents
from app.media.docx import CT, MAIN_TYPE, W
from tests.test_media_pipeline import (
    MEDIA,
    MEDIA_URL,
    mod_inputs,
    no_tmp_left,
    run_all,
    setup,
    the_message,
)
from tests.test_worker import mod_response


def make_docx(path, text="Synthetic classroom timetable", *, visual=False, extras=None):
    parts = {
        "[Content_Types].xml": (
            f'<Types xmlns="{CT[1:-1]}"><Override PartName="/word/document.xml" '
            f'ContentType="{MAIN_TYPE}"/></Types>'
        ),
        "word/document.xml": (
            f'<w:document xmlns:w="{W[1:-1]}"><w:body><w:p><w:r>'
            f"<w:t>{escape(text)}</w:t></w:r></w:p>"
            f"{'<w:drawing/>' if visual else ''}</w:body></w:document>"
        ),
        **(extras or {}),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return path.read_bytes()


@pytest.mark.parametrize("text", ["Synthetic classroom timetable", "שלום עולם שיעור חדש"])
async def test_word_and_plain_text_preserve_hebrew(tmp_path, text):
    path = tmp_path / "file"
    make_docx(path, text)
    result = await documents.extract_document(path)
    assert result["text"] == text and result["complete"]
    assert result["method"] == "docx_text_v1"
    for encoding in ("utf-8", "utf-16"):
        path.write_bytes(text.encode(encoding))
        result = await documents.extract_document(path, "text/plain; charset=utf-8")
        assert result["text"] == text and result["complete"]


@pytest.mark.parametrize("kind", ["visual", "embedded", "field", "empty", "header"])
async def test_word_coverage_includes_headers_and_rejects_unchecked_content(tmp_path, kind):
    path = tmp_path / "file"
    extra = {}
    if kind == "embedded":
        extra["word/embeddings/object.bin"] = b"opaque"
    if kind in {"field", "header"}:
        extra["word/header1.xml"] = (
            f'<w:hdr xmlns:w="{W[1:-1]}"><w:p><w:r><w:t>Header content</w:t>'
            f"{'<w:fldChar/>' if kind == 'field' else ''}</w:r></w:p></w:hdr>"
        )
    make_docx(path, "" if kind == "empty" else "Body", visual=kind == "visual", extras=extra)
    result = await documents.extract_document(path)
    assert result["complete"] is (kind == "header")
    if kind in {"field", "header"}:
        assert "Header content" in result["text"]


@pytest.mark.parametrize(
    "kind", ["doctype", "duplicate", "oversize", "binary", "malformed", "legacy", "archive"]
)
async def test_untrusted_inputs_fail_closed_without_content_leak(tmp_path, kind):
    path = tmp_path / "file"
    mime = ""
    if kind == "doctype":
        make_docx(
            path,
            extras={
                "word/header1.xml": (
                    '<!DOCTYPE x [<!ENTITY secret "private payload">]><x>&secret;</x>'
                )
            },
        )
    elif kind == "duplicate":
        make_docx(path)
        with zipfile.ZipFile(path, "a") as z, pytest.warns(UserWarning):
            z.writestr("word/document.xml", "private payload")
    elif kind == "oversize":
        path.write_text("x" * 24001)
        mime = "text/plain"
    elif kind == "binary":
        path.write_bytes(b"private\x00payload")
        mime = "text/plain"
    elif kind == "malformed":
        path.write_bytes(b"PK\x03\x04private payload")
    elif kind == "legacy":
        path.write_bytes(b"\xd0\xcf\x11\xe0private payload")
    else:
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("../private", "payload")
    with pytest.raises(PermanentError) as exc:
        await documents.extract_document(path, mime)
    assert "private" not in str(exc.value)
    assert not (tmp_path.parent / "private").exists()


@pytest.mark.parametrize("kind", ["xlsx", "pptx", "odt", "ods", "odp"])
async def test_office_text_checks_do_not_clear_unrendered_content(tmp_path, kind):
    path = tmp_path / "file"
    text = "Synthetic homework שלום"
    with zipfile.ZipFile(path, "w") as z:
        if kind == "xlsx":
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("xl/workbook.xml", "<workbook/>")
            z.writestr(
                "xl/sharedStrings.xml",
                f'<sst xmlns="{documents.S[1:-1]}"><si><t>{text}</t></si></sst>',
            )
            z.writestr(
                "xl/worksheets/sheet1.xml",
                f'<worksheet xmlns="{documents.S[1:-1]}"><c t="s"><v>0</v></c></worksheet>',
            )
        elif kind == "pptx":
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("ppt/presentation.xml", "<presentation/>")
            z.writestr("ppt/slides/slide1.xml", f'<a:t xmlns:a="{documents.A[1:-1]}">{text}</a:t>')
        else:
            z.writestr("mimetype", next(k for k, v in documents.ODF_TYPES.items() if v == kind))
            z.writestr(
                "content.xml",
                f'<o:document xmlns:o="{documents.OFFICE[1:-1]}" '
                f'xmlns:t="{documents.T[1:-1]}"><o:body><t:p>{text}</t:p></o:body></o:document>',
            )
    result = await documents.extract_document(path)
    assert text in result["text"] and not result["complete"]
    assert result["format"] == kind


@pytest.mark.parametrize(
    "visual,score,expected",
    [(False, 0, "safe"), (False, 0.99, "harmful"), (True, 0, "review"), (True, 0.99, "harmful")],
)
@pytest.mark.parametrize("local", [False, True])
@respx.mock
async def test_document_worker_classifies_content_not_filename(
    app_client, tmp_path, monkeypatch, visual, score, expected, local
):
    from app.classify.moderation import ModerationResult
    from app.classify.ollama import OllamaModerator
    from tests.test_local_safety import enable

    local_inputs = []
    if local:
        enable(monkeypatch, local=True)

        async def moderate(self, model, payload):
            local_inputs.append(payload)
            return ModerationResult({"violence": score}, score > 0, {})

        monkeypatch.setattr(OllamaModerator, "moderate", moderate)
    deps, _ = await setup(app_client)
    content = make_docx(tmp_path / "file", visual=visual)
    respx.get(url__regex=MEDIA_URL).respond(200, content=content)
    if not local:
        respx.post(URL).mock(return_value=mod_response(violence=score))
    async with deps.session_factory() as db:
        chat = Chat(wa_chat_id="synthetic-document")
        db.add(chat)
        await db.flush()
        m = Message(
            chat_id=chat.id,
            wa_message_id="document",
            type="document",
            text="Schedule",
            sent_at=datetime.now(UTC),
            status="pending",
            media={
                "instance_id": 1,
                "message_ref": "doc",
                "chat_id": "synthetic-document",
                "mimetype": None,
            },
        )
        db.add(m)
        await db.flush()
        await enqueue(db, "process_message", {"message_id": m.id})
        await db.commit()
    await run_all(deps)
    m, classifications = await the_message(app_client)
    assert m.verdict == expected
    assert "Synthetic classroom timetable" in json.dumps(local_inputs if local else mod_inputs())
    assert m.transcript is None
    assert classifications[0].scores["_meta"]["media_analysis"]["method"] == "docx_text_v1"
    from app.legacy_review import quarantine_legacy_unknowns

    async with deps.session_factory() as db:
        await quarantine_legacy_unknowns(db)
        assert (await db.get(Message, m.id)).verdict == expected
    assert no_tmp_left(app_client)
    await deps.providers.aclose()


@respx.mock
async def test_unknown_image_reaches_visual_classifier(app_client):
    deps, _ = await setup(app_client)
    respx.get(url__regex=MEDIA_URL).respond(200, content=(MEDIA / "image.png").read_bytes())
    respx.post(URL).mock(return_value=mod_response())
    async with deps.session_factory() as db:
        chat = Chat(wa_chat_id="synthetic-unknown")
        db.add(chat)
        await db.flush()
        m = Message(
            chat_id=chat.id,
            wa_message_id="unknown",
            type="other",
            text="Caption",
            sent_at=datetime.now(UTC),
            status="pending",
            media={"instance_id": 1, "message_ref": "unknown", "chat_id": "synthetic-unknown"},
        )
        db.add(m)
        await db.flush()
        await enqueue(db, "process_message", {"message_id": m.id})
        await db.commit()
    await run_all(deps)
    m, _ = await the_message(app_client)
    assert m.verdict == "safe"
    assert "data:image/jpeg;base64," in json.dumps(mod_inputs())
    assert no_tmp_left(app_client)
    await deps.providers.aclose()


async def test_document_timeout_reaps_child(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock, Mock

    proc = Mock(returncode=None, communicate=AsyncMock(side_effect=TimeoutError), wait=AsyncMock())
    monkeypatch.setattr(documents.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    with pytest.raises(PermanentError, match="timed out"):
        await documents.extract_document(tmp_path / "input")
    proc.kill.assert_called_once()
    proc.wait.assert_awaited_once()


def test_archive_expansion_limit_applies_before_xml_read(tmp_path, monkeypatch):
    path = tmp_path / "file"
    make_docx(path)
    monkeypatch.setattr(documents, "MAX_EXPANDED", 1)
    with pytest.raises(PermanentError, match="limits"):
        documents.extract(path, "")


@pytest.mark.parametrize("mime", ["text/html", "application/xml"])
async def test_markup_never_claims_rendered_coverage(tmp_path, mime):
    path = tmp_path / "file"
    path.write_text("<p>synthetic text</p>")
    assert not (await documents.extract_document(path, mime))["complete"]


@pytest.mark.parametrize(
    "kind", ["decimal", "upperLetter", "bullet", "picture", "missing", "symbol"]
)
async def test_word_list_labels_are_examined_without_clearing_custom_bullets(tmp_path, kind):
    path = tmp_path / "file"
    doc = (
        f'<w:document xmlns:w="{W[1:-1]}"><w:body><w:p><w:pPr><w:numPr>'
        '<w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
        "<w:r><w:t>Classroom task</w:t></w:r></w:p></w:body></w:document>"
    )
    fmt = kind if kind in {"decimal", "upperLetter", "bullet"} else "decimal"
    number = (
        f'<w:numbering xmlns:w="{W[1:-1]}"><w:abstractNum w:abstractNumId="0">'
        f'<w:lvl w:ilvl="0"><w:numFmt w:val="{fmt}"/>'
        '<w:lvlText w:val="Synthetic label %1"/>'
        + ('<w:lvlPicBulletId w:val="1"/>' if kind == "picture" else "")
        + ('<w:rPr><w:rFonts w:ascii="Wingdings"/></w:rPr>' if kind == "symbol" else "")
        + '</w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/>'
        "</w:num></w:numbering>"
    )
    extras = {"word/document.xml": doc}
    if kind != "missing":
        extras["word/numbering.xml"] = number
    make_docx(path, extras=extras)
    result = await documents.extract_document(path)
    assert result["complete"] is (kind in {"decimal", "upperLetter"})
    if kind != "missing":
        assert "Synthetic label %1" in result["text"]
