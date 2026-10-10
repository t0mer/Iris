"""Bounded synthetic evaluation and explicit promotion gate; no conversation exports."""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from app.classify.community import guidance, load_pack, public_manifest
from app.classify.ollama import OllamaModerator
from app.classify.thresholds import DEFAULT_THRESHOLDS, band_for
from app.config import get_settings
from app.db.models import Setting
from app.jobs.handlers import Deps
from app.jobs.queue import ClaimedJob

RESULT_KEY = "internal.learning_evaluation"


def metrics(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    harmful = sum(r["human"] == "harmful" for r in rows)
    safe = len(rows) - harmful
    tp = sum(r["human"] == "harmful" and r[field] == "harmful" for r in rows)
    fp = sum(r["human"] == "safe" and r[field] == "harmful" for r in rows)
    misses = sum(r["human"] == "harmful" and r[field] == "safe" for r in rows)
    return {
        "samples": len(rows),
        "harmful": harmful,
        "safe": safe,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": misses,
        "review": sum(r[field] == "review" for r in rows),
        "precision": tp / (tp + fp) if tp + fp else None,
        "harmful_detection_rate": tp / harmful if harmful else None,
    }


def promotion_gate(report: dict[str, Any]) -> dict[str, Any]:
    reasons = []
    if report.get("source") != "held_out_human_reviews":
        reasons.append("Synthetic checks cannot justify production promotion.")
    baseline, candidate = report["baseline"], report["candidate"]
    if candidate["samples"] < 100 or min(candidate["harmful"], candidate["safe"]) < 30:
        reasons.append(
            "At least 100 held-out labels, including 30 harmful and 30 safe, are required."
        )
    if report.get("failures"):
        reasons.append("Evaluation has failed or incomplete model requests.")
    if (
        candidate["false_negative"] > baseline["false_negative"]
        or candidate["false_positive"] > baseline["false_positive"]
    ):
        reasons.append("The candidate introduces additional missed harm or false alerts.")
    if (candidate["precision"] or 0) < 0.95 or (candidate["harmful_detection_rate"] or 0) < 0.95:
        reasons.append("Candidate precision and harmful detection must both reach 95 percent.")
    if candidate["false_positive"] >= baseline["false_positive"] and (
        candidate["harmful_detection_rate"] or 0
    ) <= (baseline["harmful_detection_rate"] or 0):
        reasons.append("The candidate must demonstrate improvement over the baseline.")
    return {"eligible": not reasons, "reasons": reasons, "automatic_promotion": False}


async def evaluate_community(model: str, base_url: str) -> dict[str, Any]:
    client = OllamaModerator(base_url, model)
    rows: list[dict[str, Any]] = []
    failures = 0
    started = time.monotonic()
    pack = await asyncio.to_thread(load_pack)
    try:
        for example in pack["evaluation"]:
            if time.monotonic() - started > 300:
                failures += len(pack["evaluation"]) - len(rows) - failures
                break
            try:
                baseline = await asyncio.wait_for(client.moderate(model, example["content"]), 30)
                candidate = await asyncio.wait_for(
                    client.moderate(
                        model, example["content"], examples=guidance(example["content"])
                    ),
                    30,
                )
                band0, _, _ = band_for(baseline.scores, DEFAULT_THRESHOLDS)
                band1, _, _ = band_for(candidate.scores, DEFAULT_THRESHOLDS)
                rows.append(
                    {
                        "human": example["verdict"],
                        "language": example["language"],
                        "baseline": "review" if band0 == "inconclusive" else band0,
                        "candidate": "review" if band1 == "inconclusive" else band1,
                        "expected_categories": example["categories"],
                        "baseline_categories": baseline.scores,
                        "candidate_categories": candidate.scores,
                    }
                )
            except Exception:
                failures += 1
        report: dict[str, Any] = {
            "source": "synthetic",
            "model": model,
            "pack": public_manifest(),
            "checked_at": datetime.now(UTC).isoformat(),
            "evaluated": len(rows),
            "failures": failures,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "baseline": metrics(rows, "baseline"),
            "candidate": metrics(rows, "candidate"),
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
    cfg = get_settings()
    if cfg.classification_provider != "ollama":
        report = {"error": "Learning evaluation requires Ollama.", "weights_updated": False}
    else:
        if job.payload.get("source") == "held_out_human_reviews":
            from app.classify.benchmark_learning import evaluate

            report = await evaluate(200, emit=False)
        else:
            report = await evaluate_community(cfg.ollama_model, cfg.ollama_base_url)
    async with deps.session_factory() as db:
        row = await db.get(Setting, RESULT_KEY)
        if row is None:
            db.add(Setting(key=RESULT_KEY, value=report))
        else:
            row.value = report
        await db.commit()
