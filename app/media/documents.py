"""Content-sniffed document dispatch with bounded, isolated text extraction."""

import asyncio
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

from app.jobs.queue import PermanentError
from app.media.docx import MAX_BYTES, MAX_CHARS, MAX_EXPANDED, MAX_PARTS, _xml
from app.media.docx import extract as extract_word
from app.media.pdf import extract as extract_pdf

UNSUPPORTED = "This attachment format cannot be analyzed yet; manual review required"
TEXT_TYPES = {
    "text/plain",
    "text/csv",
    "text/tab-separated-values",
    "text/markdown",
    "text/html",
    "text/xml",
    "application/json",
    "application/xml",
    "application/yaml",
    "text/yaml",
    "application/x-yaml",
}
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
T = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
ODF_TYPES = {
    b"application/vnd.oasis.opendocument.text": "odt",
    b"application/vnd.oasis.opendocument.spreadsheet": "ods",
    b"application/vnd.oasis.opendocument.presentation": "odp",
}


def _office(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = {p.filename for p in entries}
        if (
            len(entries) > MAX_PARTS
            or len(names) != len(entries)
            or sum(p.file_size for p in entries) > MAX_EXPANDED
            or any(p.flag_bits & 1 for p in entries)
        ):
            raise PermanentError(
                "Document archive is encrypted, ambiguous or exceeds analysis limits"
            )
        if "word/document.xml" in names:
            result = extract_word(path)
            return {**result, "method": "docx_text_v1", "format": "docx"}
        texts: list[str] = []
        count = 0

        def add(text: str) -> None:
            nonlocal count
            count += len(text) + 1
            if count > MAX_CHARS:
                raise PermanentError("Document exceeds the 24000-character analysis limit")
            texts.append(text)

        if "xl/workbook.xml" in names and "[Content_Types].xml" in names:
            format_ = "xlsx"
            strings = []
            if "xl/sharedStrings.xml" in names:
                for si in _xml(archive.read("xl/sharedStrings.xml")):
                    strings.append("".join(el.text or "" for el in si.iter(S + "t")))
            for name in sorted(names):
                if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                    for cell in _xml(archive.read(name)).iter(S + "c"):
                        if cell.get("t") == "s":
                            index = int(cell.findtext(S + "v", "-1"))
                            if not 0 <= index < len(strings):
                                raise ValueError("invalid string index")
                            add(strings[index])
                        else:
                            add(
                                " ".join(
                                    el.text or ""
                                    for el in cell.iter()
                                    if el.tag in {S + "t", S + "v", S + "f"}
                                )
                            )
                elif name.startswith("xl/comments") and name.endswith(".xml"):
                    add(" ".join(el.text or "" for el in _xml(archive.read(name)).iter(S + "t")))
        elif "ppt/presentation.xml" in names and "[Content_Types].xml" in names:
            format_ = "pptx"
            for name in sorted(names):
                if name.startswith(("ppt/slides/", "ppt/notesSlides/")) and name.endswith(".xml"):
                    add("\n".join(el.text or "" for el in _xml(archive.read(name)).iter(A + "t")))
        elif "mimetype" in names and "content.xml" in names:
            format_ = ODF_TYPES.get(archive.read("mimetype"), "")
            if not format_:
                raise PermanentError(UNSUPPORTED)
            root = _xml(archive.read("content.xml"))
            body = root.find(OFFICE + "body")
            if body is None:
                raise ValueError("missing body")
            for el in body.iter():
                if el.tag in {T + "p", T + "h"}:
                    add("".join(el.itertext()))
        else:
            raise PermanentError(UNSUPPORTED)
        # Layout, formulas, charts, masters and embedded content are not rendered.
        # Extracted text can establish harm, but cannot establish overall safety.
        return {
            "text": "\n".join(texts),
            "format": format_,
            "method": "office_text_v1",
            "complete": False,
        }


def extract(path: Path, mimetype: str) -> dict[str, Any]:
    if path.stat().st_size > MAX_BYTES:
        raise PermanentError("Document exceeds the 10 MB analysis limit")
    with path.open("rb") as stream:
        head = stream.read(16)
    if head.startswith(b"%PDF-"):
        return {**extract_pdf(path), "method": "pdf_text_v1", "format": "pdf"}
    if head.startswith(b"PK\x03\x04"):
        return _office(path)
    if mimetype not in TEXT_TYPES:
        raise PermanentError(UNSUPPORTED)
    data = path.read_bytes()
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    text = data.decode(encoding)
    if len(text) > MAX_CHARS:
        raise PermanentError("Document exceeds the 24000-character analysis limit")
    # Binary/control content must never be cleared as an empty or misleading string.
    if any(ord(c) < 32 and c not in "\t\r\n" for c in text) or "\ufffd" in text:
        raise PermanentError("Document text encoding is unreadable; manual review required")
    # Markup can render text absent from its literal source (CSS, entities, etc.).
    complete = bool(text.strip()) and mimetype not in {"text/html", "text/xml", "application/xml"}
    return {"text": text, "method": "plain_text_v1", "format": "text", "complete": complete}


async def extract_document(path: Path, mimetype: str = "") -> dict[str, Any]:
    mime = mimetype.split(";")[0].strip().lower()
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.media.documents",
        str(path),
        mime,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 30)
    except BaseException as exc:
        if proc.returncode is None:
            proc.kill()
        await asyncio.shield(proc.wait())
        if isinstance(exc, TimeoutError):
            raise PermanentError("Document analysis timed out; manual review required") from None
        raise
    if proc.returncode or len(out) > MAX_CHARS * 8:
        raise PermanentError("Document could not be read completely; manual review required")
    result: dict[str, Any] = json.loads(out)
    if result.get("error"):
        raise PermanentError(result["error"])
    return result


if __name__ == "__main__":
    import logging

    from app.media.docx import DocxReviewRequired
    from app.media.pdf import PdfReviewRequired

    logging.disable(logging.CRITICAL)
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    try:
        result = extract(Path(sys.argv[1]), sys.argv[2])
    except (PermanentError, DocxReviewRequired, PdfReviewRequired) as exc:
        result = {"error": str(exc)}
    except Exception:
        result = {"error": "Document could not be read completely; manual review required"}
    print(json.dumps(result))
