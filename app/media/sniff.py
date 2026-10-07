"""What a kept file really is, from its first bytes (never from a name or a header).

Only these formats are ever kept and served; anything else (HTML, SVG, scripts, archives) is
refused, so the portal cannot be made to serve an attacker's page from its own origin.
"""

from pathlib import Path

# content type, file extension, plays inline in a browser
Sniffed = tuple[str, str, bool]


def sniff(head: bytes) -> Sniffed | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg", True
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png", True
    if head.startswith(b"GIF8"):
        return "image/gif", "gif", True
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp", "webp", True
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "audio/wav", "wav", True
    if head.startswith(b"OggS"):
        return "audio/ogg", "ogg", True
    if head.startswith(b"fLaC"):
        return "audio/flac", "flac", True
    if head.startswith(b"#!AMR"):
        return "audio/amr", "amr", False  # browsers cannot play it: offered as a download
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm", "webm", True
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand == b"M4A ":
            return "audio/mp4", "m4a", True
        if brand == b"qt  ":
            return "video/quicktime", "mov", True
        return "video/mp4", "mp4", True
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "audio/mpeg", "mp3", True
    return None


def sniff_file(path: Path) -> Sniffed | None:
    with path.open("rb") as fh:
        return sniff(fh.read(16))


INLINE_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "audio/wav", "audio/ogg", "audio/flac",
    "video/webm", "audio/mp4", "video/quicktime", "video/mp4", "audio/mpeg",
}  # fmt: skip


def kind_of(message_type: str) -> str | None:
    """image | audio | video for the message types whose media Iris downloads, else None."""
    return {
        "image": "image",
        "sticker": "image",
        "audio": "audio",
        "voice": "audio",
        "video": "video",
    }.get(message_type)
