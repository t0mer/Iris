import json

import pytest
import respx
from pypdf import PdfWriter
from pypdf.errors import PdfReadError
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.classify.moderation import URL
from app.media import pdf
from tests.test_media_pipeline import (
    MEDIA_URL,
    mod_inputs,
    no_tmp_left,
    run_all,
    setup,
    the_message,
)
from tests.test_worker import mod_response


def make_pdf(
    path, text="Synthetic classroom timetable", *, visual=False, blank=False, password=None
):
    # PDF text-showing operators store glyphs in display order for this RTL fixture.
    if any("\u0590" <= c <= "\u05ff" for c in text):
        text = text[::-1]
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    cmap = DecodedStreamObject()
    mappings = "\n".join(f"<{i:02x}> <{ord(c):04x}>" for i, c in enumerate(text, 1))
    cmap.set_data(
        (
            "begincmap\n1 begincodespacerange\n<00> <ff>\nendcodespacerange\n"
            f"{len(text)} beginbfchar\n{mappings}\nendbfchar\nendcmap"
        ).encode()
    )
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/ToUnicode"): writer._add_object(cmap),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    encoded = bytes(range(1, len(text) + 1)).hex()
    stream.set_data(
        (
            f"BT /F1 12 Tf 20 700 Td <{encoded}> Tj ET" + (" 10 10 40 40 re f" if visual else "")
        ).encode()
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    if blank:
        writer.add_blank_page(600, 800)
    if password:
        writer.encrypt(password)
    writer.write(path)
    return path.read_bytes()


@pytest.mark.parametrize("text", ["Synthetic classroom timetable", "שלום עולם שיעור חדש"])
async def test_complete_pdf_text_including_hebrew(tmp_path, text):
    path = tmp_path / "test.pdf"
    make_pdf(path, text)
    result = await pdf.extract_pdf(path)
    assert result["complete"] and result["pages"] == 1
    assert result["text"] == text


@pytest.mark.parametrize("options", [{"visual": True}, {"blank": True}])
async def test_unchecked_pages_and_visuals_are_incomplete(tmp_path, options):
    path = tmp_path / "test.pdf"
    make_pdf(path, **options)
    assert not (await pdf.extract_pdf(path))["complete"]


@pytest.mark.parametrize("kind", ["identity", "differences", "embedded", "standard"])
async def test_unmapped_pdf_fonts_cannot_claim_complete_text(tmp_path, kind):
    from pypdf import PdfReader
    from pypdf.generic import ArrayObject, NumberObject, TextStringObject

    path = tmp_path / "font.pdf"
    make_pdf(path)
    writer = PdfWriter(clone_from=PdfReader(path))
    page = writer.pages[0]
    font = page["/Resources"]["/Font"]["/F1"].get_object()
    del font["/ToUnicode"]
    if kind == "identity":
        font[NameObject("/Subtype")] = NameObject("/Type0")
        font[NameObject("/Encoding")] = NameObject("/Identity-H")
        font[NameObject("/DescendantFonts")] = ArrayObject(
            [
                DictionaryObject(
                    {
                        NameObject("/Subtype"): NameObject("/CIDFontType2"),
                        NameObject("/BaseFont"): NameObject("/Synthetic"),
                        NameObject("/CIDSystemInfo"): DictionaryObject(
                            {
                                NameObject("/Registry"): TextStringObject("Adobe"),
                                NameObject("/Ordering"): TextStringObject("Identity"),
                                NameObject("/Supplement"): NumberObject(0),
                            }
                        ),
                    }
                )
            ]
        )
    elif kind == "differences":
        font[NameObject("/Encoding")] = DictionaryObject(
            {
                NameObject("/BaseEncoding"): NameObject("/WinAnsiEncoding"),
                NameObject("/Differences"): ArrayObject([NumberObject(65), NameObject("/Z")]),
            }
        )
    elif kind == "embedded":
        embedded = DecodedStreamObject()
        embedded.set_data(b"synthetic font bytes")
        font[NameObject("/FontDescriptor")] = DictionaryObject(
            {
                NameObject("/FontFile2"): writer._add_object(embedded),
            }
        )
    else:
        font[NameObject("/Encoding")] = NameObject("/WinAnsiEncoding")
    content = DecodedStreamObject()
    content.set_data(
        b"BT /F1 12 Tf 20 700 Td <00410042> Tj ET"
        if kind == "identity"
        else b"BT /F1 12 Tf 20 700 Td (AB) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(path)
    result = await pdf.extract_pdf(path)
    assert result["text"]
    assert result["complete"] is (kind == "standard")


@pytest.mark.parametrize("kind", ["encrypted", "malformed", "oversize", "pages", "characters"])
async def test_rejected_documents_never_return_a_prefix(tmp_path, monkeypatch, kind):
    path = tmp_path / "test.pdf"
    make_pdf(path, password="secret" if kind == "encrypted" else None)
    if kind == "malformed":
        path.write_bytes(b"%PDF-private broken content")
    elif kind == "oversize":
        monkeypatch.setattr(pdf, "MAX_BYTES", 1)
    elif kind == "pages":
        monkeypatch.setattr(pdf, "MAX_PAGES", 0)
    elif kind == "characters":
        monkeypatch.setattr(pdf, "MAX_CHARS", 1)
    with pytest.raises((pdf.PdfReviewRequired, PdfReadError)):
        pdf.extract(path)


async def test_parser_failure_does_not_expose_document_content(tmp_path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-private parser content")
    with pytest.raises(pdf.PermanentError) as failure:
        await pdf.extract_pdf(path)
    assert str(failure.value) == "PDF could not be read completely; manual review required"


async def test_timeout_kills_and_reaps_parser(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock, Mock

    proc = Mock(returncode=None, communicate=AsyncMock(side_effect=TimeoutError), wait=AsyncMock())
    monkeypatch.setattr(pdf.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    with pytest.raises(pdf.PermanentError, match="timed out"):
        await pdf.extract_pdf(tmp_path / "test.pdf")
    proc.kill.assert_called_once()
    proc.wait.assert_awaited_once()


@pytest.mark.parametrize(
    "visual,score,expected",
    [
        (False, 0, "safe"),
        (False, 0.99, "harmful"),
        (True, 0, "review"),
        (True, 0.99, "harmful"),
    ],
)
@pytest.mark.parametrize("local", [False, True])
@respx.mock
async def test_worker_uses_document_body_and_retains_unchecked_visuals(
    app_client, tmp_path, monkeypatch, visual, score, expected, local
):
    from datetime import UTC, datetime

    from app.classify.moderation import ModerationResult
    from app.classify.ollama import OllamaModerator
    from app.db.models import Chat, Message
    from app.jobs.queue import enqueue
    from tests.test_local_safety import enable

    local_inputs = []
    if local:
        enable(monkeypatch, local=True)

        async def moderate(self, model, payload):
            local_inputs.append(payload)
            return ModerationResult({"violence": score}, score > 0, {})

        monkeypatch.setattr(OllamaModerator, "moderate", moderate)

    deps, _ = await setup(app_client)
    content = make_pdf(tmp_path / "file.pdf", visual=visual)
    respx.get(url__regex=MEDIA_URL).respond(200, content=content, content_type="application/pdf")
    if not local:
        respx.post(URL).mock(return_value=mod_response(violence=score))
    async with deps.session_factory() as db:
        chat = Chat(wa_chat_id="synthetic-pdf")
        db.add(chat)
        await db.flush()
        message = Message(
            chat_id=chat.id,
            wa_message_id="pdf",
            type="document",
            text="Schedule",
            sent_at=datetime.now(UTC),
            status="pending",
            media={
                "instance_id": 1,
                "message_ref": "pdf",
                "chat_id": "synthetic-pdf",
                "mimetype": None if local else "application/pdf",
            },
        )
        db.add(message)
        await db.flush()
        await enqueue(db, "process_message", {"message_id": message.id})
        await db.commit()
    await run_all(deps)
    message, classifications = await the_message(app_client)
    assert message.verdict == expected
    assert "Synthetic classroom timetable" in json.dumps(local_inputs if local else mod_inputs())
    assert message.transcript is None  # extracted text is not retained as a voice transcript
    assert classifications[0].input_kind == "document_text"
    assert classifications[0].scores["_meta"]["media_analysis"]["complete"] is (not visual)
    from app.legacy_review import quarantine_legacy_unknowns

    async with deps.session_factory() as db:
        await quarantine_legacy_unknowns(db)
        assert (await db.get(Message, message.id)).verdict == expected
    assert no_tmp_left(app_client)
    await deps.providers.aclose()
