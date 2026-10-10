"""Optional local LoRA training; no downloads or publication without explicit CLI options."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.classify.community import load_pack, public_manifest
from scripts.prepare_learning_model import records_for


def validate(directory: Path) -> dict:
    manifest = json.loads((directory / "training-manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("contains_user_data") is not False
        or manifest["pack"]["provenance"] != "synthetic"
    ):
        raise ValueError("This public-model pipeline accepts only the synthetic learning pack")
    if manifest["pack"] != public_manifest():
        raise ValueError("Training pack does not match the reviewed repository pack")
    if set(manifest["datasets"]) != {"train.jsonl", "validation.jsonl"}:
        raise ValueError("Both independent dataset splits are required")
    seen = set()
    for name, metadata in manifest["datasets"].items():
        if name not in ("train.jsonl", "validation.jsonl"):
            raise ValueError("Unexpected dataset file")
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
            raise ValueError("Dataset changed after preparation")
        records = [json.loads(line) for line in raw.decode().splitlines()]
        source = "examples" if name == "train.jsonl" else "evaluation"
        if records != records_for(load_pack(), source) or metadata["samples"] != len(records):
            raise ValueError("Dataset is not the reviewed synthetic pack")
        for line in raw.decode().splitlines():
            record = json.loads(line)
            text = record["messages"][1]["content"]
            if text in seen:
                raise ValueError("Training and validation overlap")
            seen.add(text)
    return manifest


def train(directory: Path, output: Path, *, allow_download: bool = False) -> None:
    manifest = validate(directory)
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForSeq2Seq,
        Trainer,
        TrainingArguments,
    )

    model_id = manifest["base_model"]
    revision = manifest["base_revision"]
    options = {
        "revision": revision,
        "local_files_only": not allow_download,
        "trust_remote_code": False,
    }
    tokenizer = AutoTokenizer.from_pretrained(model_id, **options)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_id, **options)
    model = get_peft_model(
        model,
        LoraConfig(
            task_type="CAUSAL_LM",
            r=8,
            lora_alpha=16,
            target_modules="all-linear",
            lora_dropout=0.05,
        ),
    )

    def dataset(name: str) -> list[dict]:
        result = []
        for line in (directory / name).read_text(encoding="utf-8").splitlines():
            messages = json.loads(line)["messages"]
            prompt = tokenizer.apply_chat_template(
                messages[:2], tokenize=True, add_generation_prompt=True
            )
            ids = tokenizer.apply_chat_template(messages, tokenize=True)
            if len(ids) > 2048 or ids[: len(prompt)] != prompt:
                raise ValueError("Unsupported chat template or oversized training example")
            result.append(
                {
                    "input_ids": ids,
                    "attention_mask": [1] * len(ids),
                    "labels": [-100] * len(prompt) + ids[len(prompt) :],
                }
            )
        return result

    args = TrainingArguments(
        output_dir=str(output),
        num_train_epochs=1,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=0.0001,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        report_to="none",
        push_to_hub=False,
        seed=42,
        data_seed=42,
        use_cpu=not torch.cuda.is_available(),
        fp16=False,
        bf16=False,
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=dataset("train.jsonl"),
        eval_dataset=dataset("validation.jsonl"),
        processing_class=tokenizer,
        data_collator=DataCollatorForSeq2Seq(tokenizer, label_pad_token_id=-100),
    )
    trainer.train()
    model.save_pretrained(output, safe_serialization=True)
    tokenizer.save_pretrained(output)
    # An adapter is not automatically safe to publish or superior to its base model.
    manifest.update(weights_updated=True, publishable_weights=False, training_complete=True)
    (output / "training-manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(".local/learning-adapter"))
    parser.add_argument(
        "--train", action="store_true", help="Otherwise validate the training plan only"
    )
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()
    if args.train:
        train(args.dataset, args.output, allow_download=args.allow_download)
    else:
        print(json.dumps(validate(args.dataset), indent=2))
