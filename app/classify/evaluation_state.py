"""Evaluation provenance and bounded aggregate-only report history."""

import hashlib
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.classify.community import public_manifest
from app.classify.prompt import prompt_fingerprint, valid_identity
from app.classify.quality import QUALITY_POLICY
from app.config import get_settings
from app.db.models import Setting
from app.settings_store import get_setting

RESULT_KEY = "internal.learning_evaluation"
HISTORY_KEY = "internal.learning_evaluation_history"
HISTORY_LIMIT = 10


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


async def configuration_fingerprint(db: AsyncSession) -> str:
    cfg = get_settings()
    settings = {
        key: await get_setting(db, "classification." + key)
        for key in (
            "thresholds",
            "context_window_size",
            "context_max_age_hours",
            "community_learning",
            "learning_retrieval",
            "learning_embedding_model",
            "learning_min_similarity",
        )
    }
    settings.update(
        provider=await get_setting(db, "runtime.classification_provider")
        or cfg.classification_provider,
        model=await get_setting(db, "runtime.ollama_model") or cfg.ollama_model,
        endpoint=await get_setting(db, "runtime.ollama_base_url") or cfg.ollama_base_url,
        prompt=prompt_fingerprint(),
        policy=QUALITY_POLICY,
        pack=public_manifest()["sha256"],
    )
    # Provider addresses and settings are hashed, never exposed in reports.
    return fingerprint(settings)


def stale(
    report: dict[str, Any] | None,
    configuration: str,
    identity: dict[str, str] | None = None,
) -> bool:
    return bool(
        report
        and report.get("source") in {"synthetic", "held_out_human_reviews"}
        and (
            not valid_identity(identity)
            or report.get("model_identity") != identity
            or report.get("configuration_sha256") != configuration
            or report.get("quality_policy") != QUALITY_POLICY
            or report.get("prompt_sha256") != prompt_fingerprint()
        )
    )


async def save_report(db: AsyncSession, report: dict[str, Any]) -> None:
    current = await db.get(Setting, RESULT_KEY)
    history = await db.get(Setting, HISTORY_KEY)
    items = list(history.value) if history else []
    # Archive completed reports only, once per run. Keep progress in RESULT_KEY.
    for value in (current.value if current else None, report):
        if value and not value.get("pending"):
            identity = value.get("evaluation_id") or fingerprint(value)
            items = [r for r in items if (r.get("evaluation_id") or fingerprint(r)) != identity]
            items.insert(0, {**value, "evaluation_id": str(identity)})
    items = items[:HISTORY_LIMIT]
    if history is None:
        db.add(Setting(key=HISTORY_KEY, value=items))
    else:
        history.value = items
    if current is None:
        db.add(Setting(key=RESULT_KEY, value=report))
    else:
        current.value = report


async def identity_models(db: AsyncSession, model: str) -> dict[str, str]:
    models = {"classifier": model}
    embedding = await get_setting(db, "classification.learning_embedding_model")
    if embedding and await get_setting(db, "classification.learning_retrieval") == "semantic":
        models["embedding"] = str(embedding)
    return models
