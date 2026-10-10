"""Metadata-only provider storage probe. No file contents or session credentials are read."""

import json
import os
import time
from pathlib import Path


def measure(root: Path) -> dict[str, int | str]:
    total = databases = count = 0
    stack = [root]
    deadline = time.monotonic() + 30
    while stack:
        with os.scandir(stack.pop()) as entries:
            for entry in entries:
                count += 1
                if count > 500000 or time.monotonic() > deadline:
                    raise OSError("metadata scan limit reached")
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    size = entry.stat(follow_symlinks=False).st_size
                    total += size
                    if entry.name.endswith((".db", ".sqlite", ".sqlite3", "-wal", "-shm")):
                        databases += size
    return {
        "bytes": total,
        "database_bytes": databases,
        "measured_at": int(time.time()),
        "status": "measured",
    }


def main() -> None:
    root = Path("/openwa-data")
    folder = Path("/meter")
    folder.mkdir(exist_ok=True)
    while True:
        try:
            result = measure(root)
            temporary = folder / "openwa.json.tmp"
            temporary.write_text(json.dumps(result))
            temporary.chmod(0o644)
            temporary.replace(folder / "openwa.json")
        except OSError as exc:
            print("OpenWA metadata scan unavailable: " + type(exc).__name__, flush=True)
        time.sleep(60)


if __name__ == "__main__":
    main()
