"""ffmpeg/ffprobe helpers (async subprocesses, never a shell)."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from app.jobs.queue import PermanentError

_TIMEOUT = 120.0
_MAX_CONCURRENT = 2  # decoders are CPU/memory heavy: never more than this at once
_slots: asyncio.Semaphore | None = None
# Only local files/pipes: a crafted playlist or concat file must not make ffmpeg fetch URLs.
_SAFE_INPUT = ("-protocol_whitelist", "file,pipe")

# Magic-number allowlist. ffmpeg sniffs content, not extensions, and text-based "containers"
# (HLS playlists, ffconcat scripts) can name other local files, so only real media is accepted.
_SIGNATURES: tuple[tuple[int, bytes], ...] = (
    (4, b"ftyp"),  # mp4, m4a, 3gp, mov
    (0, b"OggS"),
    (0, b"ID3"),
    (0, b"fLaC"),
    (0, b"\x1a\x45\xdf\xa3"),  # mkv/webm
    (0, b"RIFF"),  # wav, webp, avi
    (0, b"GIF8"),
    (0, b"\x89PNG"),
    (0, b"\xff\xd8\xff"),  # jpeg
    (0, b"#!AMR"),
)


@dataclass(frozen=True)
class MediaInfo:
    duration: float | None
    has_audio: bool
    has_video: bool


def _sniff(path: Path) -> None:
    with path.open("rb") as fh:
        head = fh.read(16)
    is_mpeg_frames = len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0  # mp3/aac
    if not is_mpeg_frames and not any(head[o : o + len(sig)] == sig for o, sig in _SIGNATURES):
        raise PermanentError("unsupported media format")


async def _check(path: Path) -> None:
    await asyncio.to_thread(_sniff, path)


async def _run(*argv: str) -> tuple[bytes, bytes]:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(_MAX_CONCURRENT)
    async with _slots:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        except BaseException as exc:  # timeout, or the worker was cancelled mid-run
            proc.kill()
            await asyncio.shield(proc.wait())
            if isinstance(exc, TimeoutError):
                raise PermanentError("media processing timed out") from exc
            raise
    if proc.returncode != 0:
        # stderr describes the container, never message text; only its last line is kept.
        last = err.decode(errors="replace").strip().splitlines()[-1:] or [""]
        raise PermanentError(f"ffmpeg failed: {last[0][:120]}")
    return out, err


async def probe(path: Path) -> MediaInfo:
    await _check(path)
    out, _ = await _run(
        "ffprobe", "-v", "error", *_SAFE_INPUT,
        "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path),
    )  # fmt: skip
    data = json.loads(out or b"{}")
    kinds = {s.get("codec_type") for s in data.get("streams", [])}
    try:
        duration: float | None = float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        duration = None
    return MediaInfo(duration=duration, has_audio="audio" in kinds, has_video="video" in kinds)


async def extract_audio(src: Path, dst: Path) -> None:
    """Mono 16 kHz 64 kbps MP3: small, and what the transcription APIs handle best."""
    await _check(src)
    await _run(
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error", *_SAFE_INPUT, "-i", str(src),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "64k", str(dst),
    )  # fmt: skip


async def image_to_jpeg(src: Path, dst: Path, max_dim: int = 2000) -> None:
    """First frame as a bounded JPEG: converts webp/gif/png and keeps request sizes small."""
    await _check(src)
    frame = dst.with_suffix(".first-frame.webp")
    geometry = await asyncio.to_thread(_animated_webp_first_frame, src, frame)
    filters = []
    if geometry:
        width, height, x, y = geometry
        filters.append(f"pad={width}:{height}:{x}:{y}:color=white")
    filters.append(
        f"scale='min({max_dim},iw)':'min({max_dim},ih)':force_original_aspect_ratio=decrease"
    )
    try:
        await _run(
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error", *_SAFE_INPUT,
            "-i", str(frame if geometry else src), "-frames:v", "1", "-vf",
            ",".join(filters), "-q:v", "3", str(dst),
        )  # fmt: skip
        if not await asyncio.to_thread(lambda: dst.is_file() and dst.stat().st_size > 0):
            raise PermanentError(
                "Image conversion produced no readable frame; try the original media"
            )
    except PermanentError as exc:
        raise PermanentError(
            "Iris could not decode this image for AI analysis. "
            "The original may still display in your browser."
        ) from exc
    finally:
        await asyncio.to_thread(frame.unlink, missing_ok=True)


def _animated_webp_first_frame(src: Path, dst: Path) -> tuple[int, int, int, int] | None:
    """Unwrap the first ANMF frame for FFmpeg builds without animated WebP decoding.

    RIFF chunk sizes include padding; ANMF begins with a 16-byte frame header.
    Keep the frame's original compressed image/alpha chunks and canvas placement.
    No frame decompression, external tools or network access happens here.
    """
    with src.open("rb") as fh:
        header = fh.read(12)
        if header[:4] != b"RIFF" or header[8:12] != b"WEBP":
            return None
        end = int.from_bytes(header[4:8], "little") + 8
        if end > src.stat().st_size:
            raise PermanentError("Sticker data is incomplete; try retrieving the original again")
        canvas: tuple[int, int] | None = None
        alpha = 0
        animated = False
        while fh.tell() + 8 <= end:
            chunk = fh.read(8)
            tag, size = chunk[:4], int.from_bytes(chunk[4:], "little")
            if fh.tell() + size + size % 2 > end:
                raise PermanentError("Sticker data contains an invalid frame")
            if tag == b"VP8X" and size == 10:
                data = fh.read(size)
                animated = bool(data[0] & 2)
                alpha = data[0] & 16
                canvas = (
                    int.from_bytes(data[4:7], "little") + 1,
                    int.from_bytes(data[7:10], "little") + 1,
                )
                if not animated:
                    return None
            elif tag == b"ANMF" and animated and canvas:
                if not 16 < size <= 16 * 1024 * 1024:
                    raise PermanentError("Sticker frame is too large or incomplete")
                data = fh.read(size)
                x, y = (
                    int.from_bytes(data[:3], "little") * 2,
                    int.from_bytes(data[3:6], "little") * 2,
                )
                width, height = (
                    int.from_bytes(data[6:9], "little") + 1,
                    int.from_bytes(data[9:12], "little") + 1,
                )
                cw, ch = canvas
                if cw * ch > 40_000_000 or x + width > cw or y + height > ch:
                    raise PermanentError("Sticker canvas is too large or its frame is invalid")
                vp8x = (
                    bytes([alpha, 0, 0, 0])
                    + (width - 1).to_bytes(3, "little")
                    + (height - 1).to_bytes(3, "little")
                )
                payload = b"WEBPVP8X" + (10).to_bytes(4, "little") + vp8x + data[16:]
                dst.write_bytes(b"RIFF" + len(payload).to_bytes(4, "little") + payload)
                return cw, ch, x, y
            else:
                fh.seek(size, 1)
            if size % 2:
                fh.seek(1, 1)
        if animated:
            raise PermanentError("Animated sticker contains no readable frame")
        return None
