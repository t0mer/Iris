"""Versioned, public synthetic guidance. Never derives public content from user messages."""

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.classify.thresholds import DEFAULT_THRESHOLDS

PACK = Path(__file__).resolve().parents[1] / "assets" / "community-learning.json"


@lru_cache(maxsize=1)
def load_pack() -> dict[str, Any]:
    raw = PACK.read_bytes()
    pack = json.loads(raw)
    if (
        pack.get("schema_version") != 1
        or pack.get("provenance") != "synthetic"
        or pack.get("contains_user_data") is not False
    ):
        raise ValueError("Only synthetic community packs are supported")
    ids: set[str] = set()
    texts: set[str] = set()
    for split in ("examples", "evaluation"):
        for example in pack[split]:
            if example["id"] in ids or example["content"] in texts:
                raise ValueError("Duplicate or overlapping community examples")
            ids.add(example["id"])
            texts.add(example["content"])
            if example["language"] not in ("he", "en") or example["verdict"] not in (
                "safe",
                "harmful",
            ):
                raise ValueError("Invalid community label")
            if set(example["categories"]) - DEFAULT_THRESHOLDS.keys():
                raise ValueError("Invalid community categories")
            if re.search(r"https?://|@|\d{5,}", example["content"]):
                raise ValueError("Community examples cannot contain contact details")
    return {**pack, "sha256": hashlib.sha256(raw).hexdigest()}


def guidance(text: str) -> list[dict[str, Any]]:
    """Balanced, bounded references in the target language; independent of private retrieval."""
    language = "he" if re.search(r"[\u0590-\u05ff]", text) else "en"
    return [
        {
            "community_id": e["id"],
            "content": e["content"],
            "verdict": e["verdict"],
            "human_categories": e["categories"],
            "human_explanation": e.get("explanation"),
        }
        for e in load_pack()["examples"]
        if e["language"] == language
    ]


def public_manifest() -> dict[str, Any]:
    pack = load_pack()
    return {
        key: pack[key]
        for key in (
            "schema_version",
            "version",
            "sha256",
            "provenance",
            "license",
            "contains_user_data",
        )
    }
