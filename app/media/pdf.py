"""Bounded PDF text extraction in a disposable process; no scripts or URLs executed."""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from app.jobs.queue import PermanentError

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
MAX_CHARS = 24000
TIMEOUT = 30


class PdfReviewRequired(Exception):
    """Fixed, content-free reason safe to show in the review queue."""


def extract(path: Path) -> dict[str, Any]:
    from pypdf import PdfReader

    if path.stat().st_size > MAX_BYTES:
        raise PdfReviewRequired("PDF exceeds the 10 MB analysis limit")
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise PdfReviewRequired("Only PDF documents are supported for text analysis")
    reader = PdfReader(path, strict=True)
    if reader.is_encrypted:
        raise PdfReviewRequired("Encrypted PDF requires manual review")
    if not 0 < len(reader.pages) <= MAX_PAGES:
        raise PdfReviewRequired("PDF exceeds the 20-page analysis limit or has no pages")
    root = reader.root_object
    incomplete = any(
        k in root for k in ("/AcroForm", "/Names", "/OpenAction", "/AA", "/OCProperties", "/AF")
    )
    pages = []
    for page in reader.pages:
        content = page.get_contents()
        resource_ref = page.get("/Resources")
        resources = resource_ref.get_object() if resource_ref else {}
        if any(k in resources for k in ("/XObject", "/Pattern", "/Shading")):
            incomplete = True
        font_ref = resources.get("/Font")
        fonts = font_ref.get_object() if font_ref else {}
        for font_ref in fonts.values():
            font = font_ref.get_object()
            if font.get("/Subtype") == "/Type3":
                incomplete = True
            if not font.get("/ToUnicode"):
                encoding_ref = font.get("/Encoding")
                encoding = encoding_ref.get_object() if encoding_ref else None
                descriptor_ref = font.get("/FontDescriptor")
                descriptor = descriptor_ref.get_object() if descriptor_ref else {}
                embedded = any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3"))
                standard = (
                    encoding in ("/WinAnsiEncoding", "/MacRomanEncoding", "/StandardEncoding")
                    if isinstance(encoding, str)
                    else False
                )
                if (
                    font.get("/Subtype") == "/Type0"
                    or isinstance(encoding, dict)
                    or (encoding is not None and not standard)
                    or (embedded and not standard)
                ):
                    incomplete = True
        # Images, forms, vector artwork and annotations are not covered by text extraction.
        if page.get("/Annots") or content is None:
            incomplete = True
        if content is not None and any(
            op
            in {
                b"Do",
                b"INLINE IMAGE",
                b"sh",
                b"S",
                b"s",
                b"f",
                b"F",
                b"f*",
                b"B",
                b"B*",
                b"b",
                b"b*",
            }
            for _, op in content.operations
        ):
            incomplete = True
        text = page.extract_text().strip()
        if not text or "\ufffd" in text or "\x00" in text:
            incomplete = True
        pages.append(text)
        if sum(map(len, pages)) > MAX_CHARS:
            raise PdfReviewRequired("PDF exceeds the 24000-character analysis limit")
    return {
        "text": "\n\n".join(pages),
        "pages": len(pages),
        "complete": not incomplete,
    }


async def extract_pdf(path: Path) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.media.pdf",
        str(path),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), TIMEOUT)
    except BaseException as exc:
        if proc.returncode is None:
            proc.kill()
        await asyncio.shield(proc.wait())
        if isinstance(exc, TimeoutError):
            raise PermanentError("PDF analysis timed out; manual review required") from None
        raise
    if proc.returncode or len(out) > MAX_CHARS * 8:
        raise PermanentError("PDF could not be read completely; manual review required")
    result: dict[str, Any] = json.loads(out)
    if result.get("error"):
        raise PermanentError(result["error"])
    return result


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    # Linux production worker: limit decompression/parser memory and CPU independently.
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    try:
        result = extract(Path(sys.argv[1]))
    except PdfReviewRequired as exc:
        result = {"error": str(exc)}
    except Exception:
        # Parser exceptions may contain document text. Never persist or log them.
        result = {"error": "PDF could not be read completely; manual review required"}
    print(json.dumps(result))
