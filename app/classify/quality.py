"""Shared aggregate evaluation metrics and explicit promotion gates; no runtime dependencies."""

import math
from typing import Any

from app.classify.prompt import valid_identity

QUALITY_POLICY = "model-provenance-v2"


def metrics(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    if any(
        r["human"] not in {"safe", "harmful"} or r[field] not in {"safe", "harmful", "review"}
        for r in rows
    ):
        raise ValueError("Evaluation requires human safety labels and valid model verdicts")
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
        "safe_review": sum(r["human"] == "safe" and r[field] == "review" for r in rows),
        "harmful_review": sum(r["human"] == "harmful" and r[field] == "review" for r in rows),
        "precision": tp / (tp + fp) if tp + fp else None,
        "harmful_detection_rate": tp / harmful if harmful else None,
    }


def paired_comparison(rows: list[dict[str, Any]], *, unit: str = "case") -> dict[str, Any]:
    """An exact one-sided sign test; conversation identifiers never enter the report.

    Each conversation gets one vote from its net change in correctly decided messages,
    so fixing many near-duplicate messages in one chat cannot manufacture significance.
    Review is not a correct automated decision for either human safety label.
    """
    if unit not in {"case", "conversation"}:
        raise ValueError("Unknown comparison unit")
    changes: dict[Any, int] = {}
    for index, row in enumerate(rows):
        group = row["conversation"] if unit == "conversation" else index
        delta = int(row["candidate"] == row["human"]) - int(row["baseline"] == row["human"])
        changes[group] = changes.get(group, 0) + delta
    improved = sum(value > 0 for value in changes.values())
    regressed = sum(value < 0 for value in changes.values())
    discordant = improved + regressed
    probability = (
        sum(math.comb(discordant, n) for n in range(improved, discordant + 1)) / (2**discordant)
        if discordant
        else 1.0
    )
    return {
        "unit": unit,
        "units": len(changes),
        "improved": improved,
        "regressed": regressed,
        "unchanged": len(changes) - discordant,
        "one_sided_p": probability,
    }


def promotion_gate(report: dict[str, Any]) -> dict[str, Any]:
    reasons = []
    if report.get("source") != "held_out_human_reviews":
        reasons.append("Synthetic checks cannot justify production promotion.")
    if not valid_identity(report.get("model_identity")):
        reasons.append("Verified model digests are required before promotion.")
    baseline, candidate = report["baseline"], report["candidate"]
    if any(baseline[key] != candidate[key] for key in ("samples", "harmful", "safe")):
        reasons.append("Both models must evaluate the same paired human labels.")
    if (
        report.get("evaluated", candidate["samples"]) != candidate["samples"]
        or report.get("expected", candidate["samples"]) != candidate["samples"]
    ):
        reasons.append("All eligible evaluation cases must be completed.")
    if candidate["samples"] < 100 or min(candidate["harmful"], candidate["safe"]) < 30:
        reasons.append(
            "At least 100 held-out labels, including 30 harmful and 30 safe, are required."
        )
    if report.get("failures") or report.get("pending"):
        reasons.append("Evaluation has failed or incomplete model requests.")
    if candidate["review"] > baseline["review"]:
        reasons.append("The candidate increases manual review workload.")
    languages = report.get("languages", {})
    if (
        not languages
        or sum(pair["candidate"]["samples"] for pair in languages.values()) != candidate["samples"]
    ):
        reasons.append("Language-level evidence must cover every evaluated case.")
    for pair in languages.values():
        before, after = pair["baseline"], pair["candidate"]
        if not after["samples"]:
            continue
        if after["samples"] < 20 or min(after["harmful"], after["safe"]) < 5:
            reasons.append(
                "Each represented language needs 20 labels, including five harmful and five safe."
            )
        if (
            any(after[key] > before[key] for key in ("false_positive", "false_negative", "review"))
            or any(before[key] != after[key] for key in ("samples", "harmful", "safe"))
            or (after["precision"] or 0) < 0.95
            or (after["harmful_detection_rate"] or 0) < 0.95
        ):
            reasons.append("The candidate must not regress in any evaluated language.")
    paired = report.get("paired", {})
    probability = paired.get("one_sided_p")
    if (
        paired.get("unit") != "conversation"
        or isinstance(probability, bool)
        or not isinstance(probability, int | float)
        or not math.isfinite(probability)
        or not 0 <= probability <= 0.05
    ):
        reasons.append("Improvement requires a conversation-level paired sign test at p <= 0.05.")
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
    return {
        "eligible": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "automatic_promotion": False,
    }
