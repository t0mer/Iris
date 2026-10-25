"""Bounded synthetic evaluation and explicit promotion gate; no conversation exports."""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from app.classify.community import guidance, load_pack, public_manifest
from app.classify.evaluation_state import RESULT_KEY as RESULT_KEY
from app.classify.evaluation_state import configuration_fingerprint, identity_models, save_report
from app.classify.model_identity import resolve_identity
from app.classify.ollama import OllamaModerator
from app.classify.prompt import prompt_fingerprint
from app.classify.quality import QUALITY_POLICY, paired_comparison
from app.classify.quality import metrics as metrics
from app.classify.quality import promotion_gate as promotion_gate
from app.classify.thresholds import DEFAULT_THRESHOLDS, band_for
from app.config import get_settings
from app.db.models import Job, Setting
from app.jobs.handlers import Deps
from app.jobs.queue import ClaimedJob, DeferredError, TransientError, ensure_owned
from app.settings_store import reload_runtime_settings


async def evaluate_community(
    model: str,
    base_url: str,
    *,
    checkpoint: dict[str, Any] | None = None,
    request_timeout: float = 30,
) -> dict[str, Any]:
    cfg = get_settings()
    client = OllamaModerator(
        base_url,
        model,
        context_tokens=cfg.ollama_context_tokens,
        output_tokens=cfg.ollama_output_tokens,
    )
    rows: list[dict[str, Any]] = [] if checkpoint is None else checkpoint.setdefault("rows", [])
    failures = 0
    started = time.monotonic()
    pack = await asyncio.to_thread(load_pack)
    attempts: dict[str, int] = {} if checkpoint is None else checkpoint.setdefault("attempts", {})
    errors: dict[str, int] = {} if checkpoint is None else checkpoint.setdefault("errors", {})
    completed = {r.get("case_id") for r in rows}
    cases = [
        e for e in pack["evaluation"] if e["id"] not in completed and attempts.get(e["id"], 0) < 3
    ]
    if checkpoint is not None:
        cases = sorted(cases, key=lambda e: attempts.get(e["id"], 0))[:1]
    try:
        for example in cases:
            if time.monotonic() - started > 300:
                failures += len(pack["evaluation"]) - len(rows) - failures
                break
            try:
                stage = "baseline"
                attempts[example["id"]] = attempts.get(example["id"], 0) + 1
                baseline = await asyncio.wait_for(
                    client.moderate(model, example["content"]), request_timeout
                )
                stage = "candidate"
                candidate = await asyncio.wait_for(
                    client.moderate(
                        model, example["content"], examples=guidance(example["content"])
                    ),
                    request_timeout,
                )
                band0, _, _ = band_for(baseline.scores, DEFAULT_THRESHOLDS)
                band1, _, _ = band_for(candidate.scores, DEFAULT_THRESHOLDS)
                rows.append(
                    {
                        "case_id": example["id"],
                        "human": example["verdict"],
                        "language": example["language"],
                        "baseline": "review" if band0 == "inconclusive" else band0,
                        "candidate": "review" if band1 == "inconclusive" else band1,
                        "expected_categories": example["categories"],
                        "baseline_categories": baseline.scores,
                        "candidate_categories": candidate.scores,
                    }
                )
            except Exception as exc:
                failures += 1
                key = stage + ":" + type(exc).__name__
                errors[key] = errors.get(key, 0) + 1
        completed = {r.get("case_id") for r in rows}
        pending = sum(
            e["id"] not in completed and attempts.get(e["id"], 0) < 3 for e in pack["evaluation"]
        )
        if checkpoint is not None:
            failures = len(pack["evaluation"]) - len(rows) - pending
        report: dict[str, Any] = {
            "source": "synthetic",
            "quality_policy": QUALITY_POLICY,
            "prompt_sha256": prompt_fingerprint(),
            "model": model,
            "pack": public_manifest(),
            "checked_at": datetime.now(UTC).isoformat(),
            "evaluated": len(rows),
            "expected": len(pack["evaluation"]),
            "pending": pending if checkpoint is not None else 0,
            "request_errors": errors,
            "failures": failures,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "baseline": metrics(rows, "baseline"),
            "candidate": metrics(rows, "candidate"),
            "paired": paired_comparison(rows),
            "languages": {
                lang: {
                    field: metrics([r for r in rows if r["language"] == lang], field)
                    for field in ("baseline", "candidate")
                }
                for lang in ("he", "en")
            },
            "categories": {
                cat: {
                    "labelled": sum(cat in r["expected_categories"] for r in rows),
                    **{
                        field: {
                            "detected": sum(
                                cat in r["expected_categories"]
                                and r[field + "_categories"][cat] >= threshold[1]
                                for r in rows
                            ),
                            "false_positive": sum(
                                r["human"] == "safe"
                                and r[field + "_categories"][cat] >= threshold[1]
                                for r in rows
                            ),
                        }
                        for field in ("baseline", "candidate")
                    },
                }
                for cat, threshold in DEFAULT_THRESHOLDS.items()
            },
            "weights_updated": False,
            "user_data_exported": False,
        }
        report["promotion"] = promotion_gate(report)
        return report
    finally:
        await client.aclose()


async def evaluate_job(job: ClaimedJob, deps: Deps) -> None:
    async with deps.session_factory() as db:
        current = await db.get(Setting, RESULT_KEY)
        if (
            current is not None
            and current.value.get("evaluation_id") == str(job.id)
            and not current.value.get("pending")
        ):
            # A crash after saving the final report but before the worker ACK must
            # not restart the benchmark after its checkpoint has been discarded.
            return
        await reload_runtime_settings(db)
        cfg = get_settings()
        configuration = await configuration_fingerprint(db)
        models = await identity_models(db, cfg.ollama_model)
    checkpoint = job.payload.get("evaluation_checkpoint", {})
    identity = None
    if cfg.classification_provider == "ollama":
        identity = await resolve_identity(cfg.ollama_base_url, models)
        if job.payload.get("model_identity") != identity:
            checkpoint = {}
    timeout = min(float(cfg.job_timeout_seconds), 570.0)
    if cfg.classification_provider != "ollama":
        report = {"error": "Learning evaluation requires Ollama.", "weights_updated": False}
    elif job.payload.get("source") == "held_out_human_reviews":
        from app.classify.benchmark_learning import evaluate

        report = await evaluate(
            200,
            emit=False,
            checkpoint=checkpoint,
            request_timeout=max(0.1, min(120.0, (timeout - 20) / 3)),
        )
    else:
        if checkpoint.get("fingerprint") != configuration:
            checkpoint = {"fingerprint": configuration}
        report = await evaluate_community(
            cfg.ollama_model,
            cfg.ollama_base_url,
            checkpoint=checkpoint,
            request_timeout=max(0.1, min(120.0, (timeout - 10) / 2)),
        )
    if identity is not None:
        if await resolve_identity(cfg.ollama_base_url, models) != identity:
            raise TransientError("Ollama model changed during evaluation. Retry evaluation.")
        job.payload["model_identity"] = identity
        report["model_identity"] = identity
        report["promotion"] = promotion_gate(report)
    report.setdefault("configuration_sha256", configuration)
    report["evaluation_id"] = str(job.id)
    report.setdefault("checked_at", datetime.now(UTC).isoformat())
    async with deps.session_factory() as db:
        if (
            await configuration_fingerprint(db) != configuration
            or report.get("configuration_sha256") != configuration
        ):
            raise TransientError("Learning settings changed during evaluation. Retry evaluation.")
        await ensure_owned(db, job)
        await save_report(db, report)
        stored = await db.get(Job, job.id)
        if stored is not None:
            # Only in-flight checkpoints retain hashed per-case evidence. Completed
            # jobs keep aggregate reports in history, with no source identifiers.
            if report.get("pending"):
                job.payload["evaluation_checkpoint"] = checkpoint
            else:
                job.payload.pop("evaluation_checkpoint", None)
            stored.payload = dict(job.payload)
        await db.commit()
    if report.get("pending"):
        raise DeferredError(
            "Continuing learning evaluation", 1, reason="Continuing learning evaluation"
        )
