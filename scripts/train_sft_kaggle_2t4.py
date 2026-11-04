"""Train the 208 prepared DataMate traces with plain FP16 LoRA on two Kaggle T4s."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys

os.environ.setdefault('USE_TF', '0')
os.environ.setdefault('USE_TORCH', '1')
os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.coder_training.io_utils import file_hash, read_unique_jsonl, writable_output


def inspect_dataset(path, tokenizer, max_seq_len, expected_rows=None, data_train_dir="data/train"):
    """Fail rather than silently dropping/truncating any of the requested examples."""
    rows = read_unique_jsonl(path)
    if any('code' in row for row in rows):
        from scripts.build_sft_dataset import build_sft_records
        rows = build_sft_records(path, data_train_dir)
    if expected_rows is not None and len(rows) != expected_rows:
        raise ValueError(f'Expected {expected_rows} records, got {len(rows)}')
    systems = set()
    lengths = []
    for row in rows:
        messages = row['messages']
        if (row.get('prompt_format') != 'folder_readme_schema_v1'
                or len(messages) not in (3, 5)
                or [m['role'] for m in messages] != ['system'] + ['user', 'assistant'] * ((len(messages)-1)//2)
                or not all(isinstance(m['content'], str) and m['content'].strip() for m in messages)):
            raise ValueError(f"Invalid new-pipeline trace: {row['id']}")
        systems.add(messages[0]['content'])
        full = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False,
                                              return_dict=False)
        prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True,
                                                return_dict=False)
        if (not isinstance(full, list) or not isinstance(prompt, list)
                or full[:len(prompt)] != prompt or len(full) <= len(prompt)):
            raise ValueError(f"Invalid chat-template prefix: {row['id']}")
        lengths.append(dict(id=row['id'], tokens=len(full), final_tokens=len(full)-len(prompt),
                            messages=len(messages)))
    if len(systems) != 1:
        raise ValueError('All records must use the same system prompt')
    return dict(records=len(rows), messages_sha256=hashlib.sha256(
                    json.dumps(rows, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest(),
                max_seq_len=max_seq_len, min_tokens=min(r['tokens'] for r in lengths),
                max_tokens=max(r['tokens'] for r in lengths),
                overlength=[r for r in lengths if r['tokens'] > max_seq_len], lengths=lengths)


def run(args):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainerCallback, TrainingArguments, set_seed
    from peft import LoraConfig, TaskType, get_peft_model
    from peft.tuners.lora import LoraLayer
    from peft.utils.other import fsdp_auto_wrap_policy
    from scripts.train_sft_lora import prepare_dataset, DataMateDataset, DataMateCompletionOnlyCollator
    from src.coder_training.fsdp_adapter import AdapterCheckpointMixin, completion_loss_inputs, export_adapter
    from src.coder_training.checkpoints import resolve_resume_checkpoint
    from src.coder_training.t4_attention import configure_t4_sdpa

    output = writable_output(args.output_dir, args.data, args.model)
    if not args.prepare_only:
        if (not torch.cuda.is_available() or torch.cuda.device_count() != 2
                or int(os.environ.get('WORLD_SIZE', '1')) != 2
                or any(torch.cuda.get_device_capability(i) != (7, 5) for i in range(2))):
            raise RuntimeError('Use accelerate launch with exactly two T4 GPUs; no single-GPU/DDP fallback')
        # Initialize distributed state BEFORE from_pretrained for rank-zero-only CPU loading.
        training_args = TrainingArguments(
            output_dir=str(output), num_train_epochs=args.epochs,
            max_steps=2 if args.smoke else -1,
            per_device_train_batch_size=1, gradient_accumulation_steps=args.grad_accum,
            learning_rate=args.lr, warmup_ratio=0.05, lr_scheduler_type='cosine',
            fp16=True, bf16=False, optim='adamw_torch', max_grad_norm=1.0,
            gradient_checkpointing=False,
            logging_steps=1, logging_nan_inf_filter=False, report_to=[], disable_tqdm=False,
            save_strategy='steps', save_steps=1 if args.smoke else 10, save_total_limit=2,
            seed=42, data_seed=42, dataloader_num_workers=0, remove_unused_columns=False,
            fsdp='full_shard auto_wrap', fsdp_config={
                'fsdp_version': 1, 'use_orig_params': False,
                'transformer_layer_cls_to_wrap': ['Qwen2DecoderLayer'],
                'cpu_ram_efficient_loading': True, 'sync_module_states': True,
                'activation_checkpointing': True,
                'forward_prefetch': False, 'limit_all_gathers': True},
        )
        _ = training_args.device
        torch.cuda.set_device(int(os.environ['LOCAL_RANK']))
    set_seed(42)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, padding_side='right')
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    report = inspect_dataset(args.data, tokenizer, args.max_seq_len, data_train_dir=args.data_dir)
    main = args.prepare_only or torch.distributed.get_rank() == 0
    if main:
        output.mkdir(parents=True, exist_ok=True)
        (output / 'dataset_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k != 'lengths'}), flush=True)
    if report['overlength']:
        raise ValueError(f"{len(report['overlength'])} records exceed max_seq_len; see dataset_report.json. Nothing was truncated.")
    if args.prepare_only:
        return
    if output.joinpath('final_adapter').exists() and not args.resume:
        raise FileExistsError('This run already has a final_adapter. Choose a new output directory.')

    dataset = prepare_dataset(args.data, tokenizer, args.max_seq_len, data_train_dir=args.data_dir)
    assert len(dataset) == report['records']
    if args.smoke:
        longest = sorted(dataset.samples, key=lambda sample: len(sample['input_ids']), reverse=True)[:2]
        dataset = DataMateDataset([longest[i % len(longest)] for i in range(2 * args.grad_accum * 2)])
    configure_t4_sdpa()
    model = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=torch.float16, local_files_only=True, low_cpu_mem_usage=True,
        attn_implementation='sdpa',  # device_map is intentionally absent during FSDP training.
    )
    model.config.use_cache = False
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(
        task_type=TaskType.CAUSAL_LM, r=16, lora_alpha=32, lora_dropout=0.05, bias='none',
        target_modules=['q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj']))
    if args.init_adapter:
        # Warm-start: load previously trained LoRA weights (fresh optimizer/scheduler).
        from safetensors.torch import load_file
        from peft import set_peft_model_state_dict
        adapter_dir = Path(args.init_adapter)
        if (adapter_dir / 'repaired' / 'adapter_model.safetensors').is_file():
            adapter_dir = adapter_dir / 'repaired'
        init_state = load_file(str(adapter_dir / 'adapter_model.safetensors'), device='cpu')
        init_state = {k.replace('_checkpoint_wrapped_module.', ''): v for k, v in init_state.items()}
        result = set_peft_model_state_dict(model, init_state)
        unexpected = getattr(result, 'unexpected_keys', [])
        if unexpected:
            raise ValueError(f'--init-adapter has {len(unexpected)} unexpected keys, e.g. {unexpected[:3]}')
        if main:
            print(f'Warm-started LoRA from {adapter_dir} ({len(init_state)} tensors)', flush=True)
    # FSDP changes weight views between passes; let FSDP/AMP handle input precision.
    for module in model.modules():
        if isinstance(module, LoraLayer):
            module.cast_input_dtype_enabled = False
    if main:
        model.print_trainable_parameters()

    class Metrics(TrainerCallback):
        def on_log(self, arguments, state, control, logs=None, **kwargs):
            logs = logs or {}
            if any(key in logs and not math.isfinite(float(logs[key])) for key in ('loss', 'grad_norm')):
                raise RuntimeError(f'Non-finite training metrics: {logs}')
            if state.is_world_process_zero:
                with (output / 'metrics.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(dict(step=state.global_step, **logs)) + '\n')

    class CompletionTrainer(AdapterCheckpointMixin, Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            # Qwen's large vocabulary makes full-prompt logits expensive; keep only supervised positions.
            return super().compute_loss(model, completion_loss_inputs(inputs), return_outputs=return_outputs,
                                        num_items_in_batch=num_items_in_batch)

    trainer = CompletionTrainer(
        model=model, args=training_args, train_dataset=dataset, processing_class=tokenizer,
        data_collator=DataMateCompletionOnlyCollator(tokenizer.pad_token_id), callbacks=[Metrics()])
    plugin = trainer.accelerator.state.fsdp_plugin
    if (not trainer.is_fsdp_enabled or plugin is None or plugin.fsdp_version != 1
            or plugin.use_orig_params or not plugin.cpu_ram_efficient_loading):
        raise RuntimeError('Expected FSDP1 with use_orig_params=false and CPU-efficient loading')
    plugin.auto_wrap_policy = fsdp_auto_wrap_policy(trainer.model)
    config = dict(data_sha256=file_hash(args.data), model_config_sha256=file_hash(Path(args.model)/'config.json'),
                  messages_sha256=report['messages_sha256'],
                  model_dir=str(Path(args.model).resolve()), max_seq_len=args.max_seq_len, epochs=args.epochs,
                  grad_accum=args.grad_accum, lr=args.lr, lora_r=16, lora_alpha=32, seed=42,
                  smoke=args.smoke,
                  versions={p:importlib.metadata.version(p) for p in ('torch','transformers','peft','accelerate')},
                  source_sha256=file_hash(__file__))
    trainer.checkpoint_config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    resume = resolve_resume_checkpoint(args.resume, output, trainer.checkpoint_config_hash)
    if main:
        (output / 'run_config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    backup = None
    if main and os.environ.get('DATAMATE_HF_REPO'):
        from huggingface_hub import HfApi
        from src.coder_training.hub_backup import HubBackup
        prefix = os.environ['DATAMATE_HF_PREFIX'] + ('/smoke' if args.smoke else '/train')
        backup = HubBackup(HfApi(token=os.environ.get('HF_TOKEN')), os.environ['DATAMATE_HF_REPO'], output, prefix)
    trainer.hub_backup = backup
    try:
        torch.cuda.reset_peak_memory_stats()
        result = trainer.train(resume_from_checkpoint=str(resume) if resume else None)
        if not math.isfinite(result.training_loss):
            raise RuntimeError('Non-finite final loss')
        # Keep a complete checkpoint if the final step falls between save intervals.
        checkpoint = output / f'checkpoint-{trainer.state.global_step}'
        if not (checkpoint / 'checkpoint_complete.json').is_file():
            trainer._save_checkpoint(trainer.model_wrapped, trial=None)
        if args.smoke:
            trainer._load_from_checkpoint(str(checkpoint), trainer.model_wrapped)
            trainer._load_optimizer_and_scheduler(str(checkpoint))
            trainer._load_scaler(str(checkpoint))
        export_adapter(trainer, str(output / 'final_adapter'))
        if backup:
            backup.submit(output / 'final_adapter')
        rank_report = dict(rank=torch.distributed.get_rank(), steps=trainer.state.global_step,
                           loss=result.training_loss, peak_vram_gib=torch.cuda.max_memory_allocated()/2**30)
        ranks = [None, None]
        torch.distributed.all_gather_object(ranks, rank_report)
        if main:
            trainer.save_metrics('train', dict(result.metrics, train_samples=len(dataset), source_samples=report['records']))
            (output / 'completed.json').write_text(json.dumps(dict(config=config, ranks=ranks,
                  status='passed', checkpoint_restore_checked=args.smoke), indent=2), encoding='utf-8')
    finally:
        if backup:
            backup.finish()
    trainer.accelerator.wait_for_everyone()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True, help='Local Instruct checkpoint directory')
    parser.add_argument('--data', required=True)
    parser.add_argument('--data-dir', default='data/train', help='Train split for IDs/code records')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--max-seq-len', type=int, default=8192)
    parser.add_argument('--epochs', type=float, default=3.0)
    parser.add_argument('--grad-accum', type=int, default=4)
    parser.add_argument('--lr', type=float, default=1e-4)
    parser.add_argument('--resume', default='', help='Empty, latest, or complete checkpoint path')
    parser.add_argument('--init-adapter', default='',
                        help='Warm-start from a trained LoRA adapter dir (e.g. Model/V2); optimizer restarts fresh')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    if args.max_seq_len < 1 or args.grad_accum < 1 or args.epochs <= 0 or args.lr <= 0:
        parser.error('Sequence length, epochs, accumulation and LR must be positive')
    if args.smoke and args.resume:
        parser.error('Run smoke fresh; resume is for the full training run')
    return args


if __name__ == '__main__':
    run(parse_args())
