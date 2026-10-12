"""Prepare a public synthetic dataset and a reproducible, private-by-default training plan."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.classify.community import load_pack, public_manifest
from app.classify.prompt import moderation_prompt, prompt_fingerprint
from app.classify.thresholds import DEFAULT_THRESHOLDS


def model_identity(base_model: str, revision: str) -> dict:
    directory = Path(base_model)
    if directory.is_dir():
        names = {
            "config.json",
            "generation_config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "tokenizer.model",
            "vocab.json",
            "merges.txt",
            "added_tokens.json",
        }
        files = {}
        for file in sorted(directory.rglob("*")):
            if file.is_file() and (
                file.name in names
                or file.suffix == ".safetensors"
                or file.name.endswith(".safetensors.index.json")
            ):
                with file.open("rb") as stream:
                    files[file.relative_to(directory).as_posix()] = hashlib.file_digest(
                        stream, "sha256"
                    ).hexdigest()
        if "config.json" not in files or not revision.strip():
            raise ValueError("Local models require config.json and a revision label")
        return {"kind": "local", "files": files}
    if not re.fullmatch(r"(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})", revision):
        raise ValueError("Remote models require a full pinned commit, not a branch or tag")
    return {"kind": "remote", "commit": revision.lower()}


def records_for(pack: dict, source: str) -> list[dict]:
    records = []
    for example in pack[source]:
        scores = {
            category: float(category in example["categories"]) for category in DEFAULT_THRESHOLDS
        }
        records.append(
            {
                "id": example["id"],
                "language": example["language"],
                "messages": [
                    {
                        "role": "system",
                        "content": moderation_prompt(),
                    },
                    {"role": "user", "content": example["content"]},
                    {"role": "assistant", "content": json.dumps(scores)},
                ],
            }
        )
    return records


def prepare(output: Path, base_model: str, revision: str) -> dict:
    identity = model_identity(base_model, revision)
    pack = load_pack()
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    for source, name in (("examples", "train.jsonl"), ("evaluation", "validation.jsonl")):
        records = records_for(pack, source)
        raw = (
            "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"
        ).encode()
        (output / name).write_bytes(raw)
        files[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "samples": len(records)}
    manifest = {
        "schema_version": 1,
        "pack": public_manifest(),
        "base_model": base_model,
        "base_revision": revision,
        "base_identity": identity,
        "prompt_sha256": prompt_fingerprint(),
        "datasets": files,
        "contains_user_data": False,
        "privacy": "Synthetic inputs only; no access to Iris database or user exports.",
        "publishable_weights": False,
        "reason": "Training and independent quality/privacy checks are required before release.",
    }
    (output / "training-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/learning-training"))
    parser.add_argument("--base-model", required=True)
    parser.add_argument(
        "--revision", required=True, help="Pinned base model commit or local revision"
    )
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, args.base_model, args.revision), indent=2))
