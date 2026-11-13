"""Exercise optional adapter training offline with tiny random weights and synthetic data."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def smoke(root: Path) -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from tokenizers.trainers import WordLevelTrainer
    from transformers import LlamaConfig, LlamaForCausalLM, PreTrainedTokenizerFast

    from app.classify.community import load_pack
    from scripts.evaluate_learning_adapter import evaluate
    from scripts.prepare_learning_model import prepare, records_for
    from scripts.train_learning_adapter import train

    torch.set_num_threads(2)
    torch.manual_seed(42)
    base = root.resolve() / "random-base"
    base.mkdir(parents=True, exist_ok=True)
    raw = Tokenizer(WordLevel(unk_token="[UNK]"))
    raw.pre_tokenizer = Whitespace()
    records = records_for(load_pack(), "examples") + records_for(load_pack(), "evaluation")
    raw.train_from_iterator(
        [m["content"] for r in records for m in r["messages"]] + ["system user assistant"],
        WordLevelTrainer(special_tokens=["[UNK]", "[PAD]", "[BOS]", "[EOS]"]),
    )
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=raw,
        unk_token="[UNK]",
        pad_token="[PAD]",
        bos_token="[BOS]",
        eos_token="[EOS]",
    )
    tokenizer.chat_template = (
        "{{ bos_token }}{% for message in messages %}"
        "{{ message['role'] + ': ' + message['content'] + eos_token }}{% endfor %}"
        "{% if add_generation_prompt %}{{ 'assistant: ' }}{% endif %}"
    )
    tokenizer.save_pretrained(base)
    model = LlamaForCausalLM(
        LlamaConfig(
            vocab_size=len(tokenizer),
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=1,
            num_attention_heads=2,
            num_key_value_heads=2,
            max_position_embeddings=2048,
            pad_token_id=tokenizer.pad_token_id,
            bos_token_id=tokenizer.bos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    )
    model.save_pretrained(base)
    prepare(root / "dataset", str(base), "offline-random-smoke-v1")
    train(root / "dataset", root / "adapter")
    assert (root / "adapter" / "adapter_model.safetensors").stat().st_size > 0
    from safetensors.torch import load_file

    weights = load_file(root / "adapter" / "adapter_model.safetensors")
    updates = [v for k, v in weights.items() if "lora_B" in k]
    assert updates and all(v.count_nonzero().item() > 0 for v in updates)
    report = evaluate(root / "dataset", root / "adapter", max_new_tokens=256)
    assert report["expected"] == len(records_for(load_pack(), "evaluation"))
    assert not report["promotion"]["eligible"] and not report["publishable_weights"]
    print("Generated-output evaluation completed; publication remains blocked.")
    print("Offline training smoke passed. Random demonstration weights; not a production model.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/learning-training-smoke"))
    smoke(parser.parse_args().output)
