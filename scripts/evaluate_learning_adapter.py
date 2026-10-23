"""Compare a local adapter with its pinned base using synthetic cases; never publish weights."""

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.classify.community import load_pack, public_manifest
from app.classify.prompt import prompt_fingerprint
from app.classify.quality import QUALITY_POLICY, metrics, paired_comparison, promotion_gate
from app.classify.thresholds import DEFAULT_THRESHOLDS, band_for
from scripts.train_learning_adapter import validate, verify_adapter


def parse_scores(text: str) -> dict[str, float]:
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != set(DEFAULT_THRESHOLDS):
        raise ValueError("Incomplete classification output")
    if any(
        isinstance(v, bool)
        or not isinstance(v, int | float)
        or not math.isfinite(v)
        or not 0 <= v <= 1
        for v in value.values()
    ):
        raise ValueError("Invalid classification scores")
    return {key: float(v) for key, v in value.items()}


def summarize_predictions(baseline: list[str], candidate: list[str]) -> dict:
    cases = load_pack()["evaluation"]
    if len(baseline) != len(cases) or len(candidate) != len(cases):
        raise ValueError("Both models must evaluate the entire independent split")
    rows = []
    errors = {"baseline": 0, "candidate": 0}
    for case, before, after in zip(cases, baseline, candidate, strict=True):
        scores = {}
        for stage, output in (("baseline", before), ("candidate", after)):
            try:
                scores[stage] = parse_scores(output)
            except (ValueError, TypeError):
                errors[stage] += 1
        if len(scores) != 2:
            continue  # malformed output is a failure, never an assumed safe verdict
        row = {
            "human": case["verdict"],
            "language": case["language"],
            "expected_categories": case["categories"],
        }
        for stage in scores:
            band, _, _ = band_for(scores[stage], DEFAULT_THRESHOLDS)
            row[stage] = "review" if band == "inconclusive" else band
            row[stage + "_scores"] = scores[stage]
        rows.append(row)
    report = {
        "source": "synthetic_adapter",
        "quality_policy": QUALITY_POLICY,
        "prompt_sha256": prompt_fingerprint(),
        "pack": public_manifest(),
        "expected": len(cases),
        "evaluated": len(rows),
        "failures": len(cases) - len(rows),
        "invalid_outputs": errors,
        "baseline": metrics(rows, "baseline"),
        "candidate": metrics(rows, "candidate"),
        "paired": paired_comparison(rows),
        "languages": {
            language: {
                stage: metrics([r for r in rows if r["language"] == language], stage)
                for stage in ("baseline", "candidate")
            }
            for language in ("he", "en")
        },
        "categories": {
            category: {
                "labelled": sum(category in r["expected_categories"] for r in rows),
                **{
                    stage: {
                        "detected": sum(
                            category in r["expected_categories"]
                            and r[stage + "_scores"][category] >= threshold[1]
                            for r in rows
                        ),
                        "false_positive": sum(
                            r["human"] == "safe" and r[stage + "_scores"][category] >= threshold[1]
                            for r in rows
                        ),
                    }
                    for stage in ("baseline", "candidate")
                },
            }
            for category, threshold in DEFAULT_THRESHOLDS.items()
        },
        "user_data_exported": False,
        "publishable_weights": False,
    }
    report["promotion"] = promotion_gate(report)
    return report


def evaluate(
    directory: Path, adapter: Path, *, max_new_tokens: int = 256, allow_download: bool = False
) -> dict:
    if not 8 <= max_new_tokens <= 512:
        raise ValueError("Generation must be bounded to 8–512 new tokens")
    manifest = validate(directory)
    trained = json.loads((adapter / "training-manifest.json").read_text(encoding="utf-8"))
    for key in (
        "pack",
        "datasets",
        "base_model",
        "base_revision",
        "base_identity",
        "prompt_sha256",
    ):
        if trained.get(key) != manifest[key]:
            raise ValueError("Adapter does not match this reviewed training plan")
    identity = verify_adapter(adapter, trained)

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    options = {
        "revision": manifest["base_revision"],
        "local_files_only": not allow_download,
        "trust_remote_code": False,
    }
    tokenizer = AutoTokenizer.from_pretrained(manifest["base_model"], **options)
    model = AutoModelForCausalLM.from_pretrained(manifest["base_model"], **options)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    records = [
        json.loads(line)
        for line in (directory / "validation.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    def predict(active) -> list[str]:
        active.eval()
        results = []
        with torch.inference_mode():
            for record in records:
                inputs = tokenizer.apply_chat_template(
                    record["messages"][:2],
                    tokenize=True,
                    add_generation_prompt=True,
                    return_dict=True,
                    return_tensors="pt",
                ).to(device)
                length = inputs["input_ids"].shape[1]
                if length > 2048:
                    raise ValueError("Oversized evaluation input")
                output = active.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    pad_token_id=tokenizer.pad_token_id
                    if tokenizer.pad_token_id is not None
                    else tokenizer.eos_token_id,
                )
                results.append(tokenizer.decode(output[0, length:], skip_special_tokens=True))
        return results

    baseline = predict(model)
    candidate = predict(PeftModel.from_pretrained(model, adapter, local_files_only=True))
    report = summarize_predictions(baseline, candidate)
    # Do not report a valid comparison if files changed during model loading/inference.
    verify_adapter(adapter, trained)
    report["adapter_sha256"] = identity["adapter_model.safetensors"]
    report["adapter_files"] = identity
    report["max_new_tokens"] = max_new_tokens
    (adapter / "evaluation-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            evaluate(
                args.dataset,
                args.adapter,
                max_new_tokens=args.max_new_tokens,
                allow_download=args.allow_download,
            ),
            indent=2,
        )
    )
