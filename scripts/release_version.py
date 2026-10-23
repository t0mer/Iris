"""Validate release tags before any publishing credentials are used."""

import re
import sys
from datetime import UTC, date, datetime


def release_version(tag: str) -> dict[str, str]:
    match = re.fullmatch(
        r"v?([0-9]{4}\.(?:0?[1-9]|1[0-2])\.(?:0|[1-9][0-9]*)(?:-(?:alpha|beta|rc)\.[1-9][0-9]*)?)",
        tag,
    )
    if not match:
        raise ValueError("Expected YYYY.M.PATCH or YYYY.M.PATCH-beta.N (alpha/rc also supported)")
    version = match.group(1)
    return {"tag": tag, "version": version, "prerelease": str("-" in version).lower()}


def next_version(tags: list[str], today: date) -> str:
    patches = []
    for tag in tags:
        try:
            result = release_version(tag)
        except ValueError:
            continue
        if result["prerelease"] == "true":
            continue
        year, month, patch = map(int, result["version"].split("."))
        if (year, month) == (today.year, today.month):
            patches.append(patch)
    return f"{today.year}.{today.month}.{max(patches, default=-1) + 1}"


if __name__ == "__main__":
    if sys.argv[1:] == ["--next"]:
        print(next_version(sys.stdin.read().splitlines(), datetime.now(UTC).date()))
    else:
        for key, value in release_version(sys.argv[1]).items():
            print(f"{key}={value}")
