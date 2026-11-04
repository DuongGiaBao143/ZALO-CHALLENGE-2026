"""Stand-alone SFT LoRA fine-tuning script for Qwen2.5-Coder-7B-Instruct on DataMate.

Features:
- Compatible with Colab A100 / L4 / T4 / Multi-GPU.
- Supports completion-only loss (supervision only on Python code assistant turns).
- Full ChatML compatibility with Qwen2.5-Coder tokenization.
- Automatic precision detection (bfloat16 for Ampere/Ada/Hopper, float16 for Turing/T4).
- Saves LoRA adapter and training metrics to output_dir.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import torch
from peft import LoraConfig, PeftModel, get_peft_model, TaskType
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    Trainer,
    TrainingArguments,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class DataMateDataset(torch.utils.data.Dataset):
    """Native PyTorch Dataset for clean sample fetching without HF Arrow/getitems quirks."""

    def __init__(self, samples: List[Dict[str, Any]]):
        self.samples = samples

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        return self.samples[idx]


class DataMateCompletionOnlyCollator:
    """Custom standalone collator supporting both list-of-dicts and dict-of-lists, padding with PyTorch C++ utils."""

    def __init__(self, pad_token_id: int, pad_to_multiple_of: int = 8):
        self.pad_token_id = pad_token_id
        self.pad_to_multiple_of = pad_to_multiple_of

    def __call__(self, features: Any) -> Dict[str, torch.Tensor]:
        if isinstance(features, dict):
            raw_input_ids = features["input_ids"]
            raw_attention_mask = features.get("attention_mask")
            raw_labels = features.get("labels")
        elif isinstance(features, list):
            if isinstance(features[0], dict):
                raw_input_ids = [f["input_ids"] for f in features]
                raw_attention_mask = [f.get("attention_mask") for f in features]
                raw_labels = [f.get("labels") for f in features]
            else:
                raw_input_ids = features
                raw_attention_mask = None
                raw_labels = None
        else:
            raise TypeError(f"Unexpected features type: {type(features)}")

        def to_tensor_list(items):
            res = []
            for item in items:
                if isinstance(item, torch.Tensor):
                    res.append(item.long())
                elif isinstance(item, dict):
                    res.append(torch.tensor(item.get("input_ids", item), dtype=torch.long))
                else:
                    res.append(torch.tensor(item, dtype=torch.long))
            return res

        tensor_input_ids = to_tensor_list(raw_input_ids)
        tensor_labels = to_tensor_list(raw_labels) if raw_labels and raw_labels[0] is not None else None

        padded_input_ids = torch.nn.utils.rnn.pad_sequence(
            tensor_input_ids,
            batch_first=True,
            padding_value=self.pad_token_id,
        )

        if raw_attention_mask and raw_attention_mask[0] is not None:
            tensor_mask = to_tensor_list(raw_attention_mask)
            padded_mask = torch.nn.utils.rnn.pad_sequence(
                tensor_mask,
                batch_first=True,
                padding_value=0,
            )
        else:
            padded_mask = (padded_input_ids != self.pad_token_id).long()

        if tensor_labels is not None:
            padded_labels = torch.nn.utils.rnn.pad_sequence(
                tensor_labels,
                batch_first=True,
                padding_value=-100,
            )
        else:
            padded_labels = None

        if self.pad_to_multiple_of and (padded_input_ids.shape[1] % self.pad_to_multiple_of != 0):
            seq_len = padded_input_ids.shape[1]
            pad_len = ((seq_len // self.pad_to_multiple_of) + 1) * self.pad_to_multiple_of - seq_len
            pad_input = torch.full((padded_input_ids.shape[0], pad_len), self.pad_token_id, dtype=torch.long, device=padded_input_ids.device)
            padded_input_ids = torch.cat([padded_input_ids, pad_input], dim=1)

            pad_mask = torch.zeros((padded_mask.shape[0], pad_len), dtype=torch.long, device=padded_mask.device)
            padded_mask = torch.cat([padded_mask, pad_mask], dim=1)

            if padded_labels is not None:
                pad_lab = torch.full((padded_labels.shape[0], pad_len), -100, dtype=torch.long, device=padded_labels.device)
                padded_labels = torch.cat([padded_labels, pad_lab], dim=1)

        batch = {
            "input_ids": padded_input_ids,
            "attention_mask": padded_mask,
        }
        if padded_labels is not None:
            batch["labels"] = padded_labels
        return batch


def build_safe_training_arguments(**kwargs) -> TrainingArguments:
    """Build TrainingArguments safely across different transformers versions."""
    import inspect
    sig = inspect.signature(TrainingArguments.__init__)
    valid_params = set(sig.parameters.keys())

    # Fallback warmup_ratio to warmup_steps if not in signature
    if "warmup_ratio" not in valid_params and "warmup_ratio" in kwargs:
        kwargs.pop("warmup_ratio")
        kwargs["warmup_steps"] = 5

    filtered = {k: v for k, v in kwargs.items() if k in valid_params}
    return TrainingArguments(**filtered)


def prepare_dataset(
    jsonl_path: str,
    tokenizer: Any,
    max_seq_len: int = 8192,
    data_train_dir: str = "data/train",
) -> DataMateDataset:
    """Load JSONL ChatML records and prepare input_ids + completion-only labels."""
    logger.info("Loading SFT dataset from %s", jsonl_path)
    records = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    if any("code" in item for item in records):
        from scripts.build_sft_dataset import build_sft_records
        records = build_sft_records(jsonl_path, data_train_dir)

    logger.info("Found %d records. Tokenizing with completion-only masking...", len(records))

    tokenized_samples = []
    skipped_too_long = 0

    for idx, item in enumerate(records):
        messages = item["messages"]
        if not messages or messages[-1].get("role") != "assistant":
            raise ValueError(f"SFT record {idx} must end with an assistant completion")
        prompt_msgs = messages[:-1]

        # 1. Tokenize prompt only (with add_generation_prompt=True)
        prompt_ids = tokenizer.apply_chat_template(
            prompt_msgs,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=False,  # Transformers v5 otherwise returns BatchEncoding.
        )

        # 2. Tokenize full conversation
        full_ids = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=False,
            return_dict=False,
        )

        if not all(isinstance(ids, list) and all(type(token) is int for token in ids)
                   for ids in (prompt_ids, full_ids)):
            raise TypeError(f"SFT record {idx}: chat template must return lists of integer token IDs")
        prompt_len = len(prompt_ids)
        full_len = len(full_ids)
        if full_ids[:prompt_len] != prompt_ids or full_len <= prompt_len:
            raise ValueError(f"SFT record {idx}: prompt prefix mismatch or no completion tokens")

        if full_len > max_seq_len:
            skipped_too_long += 1
            # If slightly over max_seq_len, we can truncate from the middle if allowed,
            # or skip to maintain dataset purity.
            continue

        # 3. Create labels: mask prompt tokens with -100 so loss is ONLY on assistant code
        labels = [-100] * prompt_len + full_ids[prompt_len:]
        attention_mask = [1] * full_len

        tokenized_samples.append({
            "input_ids": full_ids,
            "attention_mask": attention_mask,
            "labels": labels,
        })

    logger.info("Tokenization complete: %d retained, %d skipped (> %d tokens)",
                len(tokenized_samples), skipped_too_long, max_seq_len)

    if not tokenized_samples:
        raise ValueError(f"No samples retained within max_seq_len={max_seq_len}!")

    return DataMateDataset(tokenized_samples)


def train_sft(
    model_name_or_path: str,
    data_path: str,
    output_dir: str,
    resume_adapter: str | None = None,
    max_seq_len: int = 8192,
    num_train_epochs: float = 3.0,
    per_device_batch_size: int = 1,
    gradient_accumulation_steps: int = 4,
    learning_rate: float = 2e-4,
    lora_r: int = 16,
    lora_alpha: int = 32,
    lora_dropout: float = 0.05,
    seed: int = 42,
    data_train_dir: str = "data/train",
) -> None:
    logger.info("=== Starting DataMate SFT LoRA Fine-Tuning ===")
    logger.info("Model: %s", model_name_or_path)
    logger.info("Dataset: %s", data_path)
    logger.info("Output dir: %s", output_dir)

    # 1. Precision configuration
    use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    use_fp16 = torch.cuda.is_available() and not use_bf16
    dtype = torch.bfloat16 if use_bf16 else (torch.float16 if use_fp16 else torch.float32)
    logger.info("Compute precision: %s (bf16=%s, fp16=%s)", dtype, use_bf16, use_fp16)

    # 2. Tokenizer
    logger.info("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(
        model_name_or_path,
        trust_remote_code=True,
        padding_side="right",
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Validate tokenization and collation before loading the large model.
    dataset = prepare_dataset(data_path, tokenizer, max_seq_len=max_seq_len, data_train_dir=data_train_dir)
    data_collator = DataMateCompletionOnlyCollator(
        pad_token_id=tokenizer.pad_token_id,
        pad_to_multiple_of=8,
    )
    data_collator([dataset[0]])

    # 3. Model
    logger.info("Loading base model in %s...", dtype)
    try:
        model = AutoModelForCausalLM.from_pretrained(
            model_name_or_path,
            dtype=dtype,
            device_map="auto",
            trust_remote_code=True,
        )
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(
            model_name_or_path,
            torch_dtype=dtype,
            device_map="auto",
            trust_remote_code=True,
        )
    model.config.use_cache = False  # Recommended for training with gradient checkpointing
    model.enable_input_require_grads()

    # 4. LoRA Setup
    if resume_adapter and os.path.exists(resume_adapter):
        logger.info("Resuming LoRA training from existing adapter: %s", resume_adapter)
        model = PeftModel.from_pretrained(model, resume_adapter, is_trainable=True)
    else:
        logger.info("Configuring fresh LoRA (r=%d, alpha=%d, dropout=%.2f)...", lora_r, lora_alpha, lora_dropout)
        lora_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=lora_r,
            lora_alpha=lora_alpha,
            lora_dropout=lora_dropout,
            bias="none",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        )
        model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # 6. Training Arguments
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    training_args = build_safe_training_arguments(
        output_dir=str(out_path / "checkpoints"),
        num_train_epochs=num_train_epochs,
        per_device_train_batch_size=per_device_batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        learning_rate=learning_rate,
        lr_scheduler_type="cosine",
        warmup_steps=5,
        logging_steps=5,
        save_strategy="epoch",
        save_total_limit=2,
        bf16=use_bf16,
        fp16=use_fp16,
        seed=seed,
        report_to="none",
        dataloader_num_workers=0,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=data_collator,
    )

    logger.info("Beginning training loop...")
    train_result = trainer.train()

    # 7. Save final adapter
    final_adapter_dir = out_path / "final_adapter"
    logger.info("Saving final adapter weights to %s...", final_adapter_dir)
    model.save_pretrained(str(final_adapter_dir))
    tokenizer.save_pretrained(str(final_adapter_dir))

    # Save training metrics
    metrics = train_result.metrics
    metrics["train_samples"] = len(dataset)
    trainer.log_metrics("train", metrics)
    trainer.save_metrics("train", metrics)
    trainer.save_state()

    logger.info("=== DataMate SFT LoRA Training Complete! ===")
    logger.info("Trained adapter saved at: %s", final_adapter_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DataMate SFT LoRA Fine-Tuning")
    parser.add_argument("--model", type=str, default="Qwen/Qwen2.5-Coder-7B-Instruct", help="Base model path or HF hub id")
    parser.add_argument("--data", type=str, default="result/sft_train_ready.jsonl", help="Path to clean SFT jsonl dataset")
    parser.add_argument("--data-dir", default="data/train", help="Train split used to rebuild prompts for IDs/code records")
    parser.add_argument("--output_dir", type=str, default="result/sft_adapter_qwen7b", help="Directory to save adapter")
    parser.add_argument("--resume_adapter", type=str, default=None, help="Optional existing adapter directory to continue training from")
    parser.add_argument("--max_seq_len", type=int, default=12288, help="Max sequence length")
    parser.add_argument("--epochs", type=float, default=3.0, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=1, help="Per device batch size")
    parser.add_argument("--grad_accum", type=int, default=4, help="Gradient accumulation steps")
    parser.add_argument("--lr", type=float, default=1e-4, help="Learning rate")
    parser.add_argument("--lora_r", type=int, default=16, help="LoRA rank")
    parser.add_argument("--lora_alpha", type=int, default=32, help="LoRA alpha")
    args = parser.parse_args()

    train_sft(
        model_name_or_path=args.model,
        data_path=args.data,
        data_train_dir=args.data_dir,
        output_dir=args.output_dir,
        resume_adapter=args.resume_adapter,
        max_seq_len=args.max_seq_len,
        num_train_epochs=args.epochs,
        per_device_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
    )
