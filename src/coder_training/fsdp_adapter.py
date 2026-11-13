"""Completion logits and adapter-only FSDP export/restore for Kaggle 7B training."""
from pathlib import Path


def prepare_fsdp_qlora_model(model):
    """Shard frozen embeddings/head separately to avoid a full-vocabulary FP32 broadcast peak."""
    import torch
    from peft.utils.other import fsdp_auto_wrap_policy
    policy = fsdp_auto_wrap_policy(model)
    vocabulary_modules = {model.get_input_embeddings(), model.get_output_embeddings()}
    for module in vocabulary_modules:
        if module is None or any(p.requires_grad or type(p).__name__ == 'Params4bit' for p in module.parameters()):
            raise ValueError('Expected frozen, unquantized input embeddings and output head')
        # Their FP16 AMP compute stays the same; keep packed NF4 storage elsewhere in FP32.
        module.to(dtype=torch.float16)

    def wrap_policy(module, recurse, nonwrapped_numel):
        return module in vocabulary_modules or policy(module, recurse, nonwrapped_numel)

    return wrap_policy


def completion_loss_inputs(inputs):
    """Select only logits predicting supervised tokens, preserving the causal shift exactly."""
    import torch
    labels = inputs['labels']
    positions = torch.where((labels[:, 1:] != -100).any(dim=0))[0]
    if positions.numel() == 0:
        raise ValueError('No supervised next-token labels in batch')
    return dict(inputs, logits_to_keep=positions,
                shift_labels=labels.index_select(1, positions + 1).contiguous())


def collect_lora_state(wrapped_model, rank0):
    """All ranks gather one LoRA leaf at a time; never gather the 14B base onto host RAM."""
    from torch.distributed.fsdp import FullyShardedDataParallel as FSDP
    state = {}
    units = [(name, module) for name, module in wrapped_model.named_modules()
             if isinstance(module, FSDP) and ('.lora_A.' in name or '.lora_B.' in name)]
    if not units:
        raise RuntimeError('No separately wrapped LoRA leaves found; refusing full-base export')
    for name, unit in units:
        clean_name = name.replace('_fsdp_wrapped_module.', '').replace('_checkpoint_wrapped_module.', '')
        # A single LoRA leaf is small: gather on GPU then copy it to CPU. This also
        # supports NO_SHARD probes, for which summon(offload_to_cpu=True) is unsupported.
        with FSDP.summon_full_params(unit, recurse=False, writeback=False, rank0_only=True, offload_to_cpu=False):
            if rank0:
                for key, value in unit.module.named_parameters(recurse=False):
                    if not value.requires_grad:
                        raise RuntimeError('Frozen parameter unexpectedly included in adapter gather')
                    state[f'{clean_name}.{key}'] = value.detach().cpu().clone()
    if rank0 and not state:
        raise RuntimeError('Empty gathered adapter state')
    return state


def load_lora_state(wrapped_model, checkpoint):
    """Restore only LoRA leaves after FSDP wrapping, without gathering frozen weights."""
    import torch
    from safetensors.torch import load_file
    from torch.distributed.fsdp import FullyShardedDataParallel as FSDP
    # Initialize the root before summoning leaves, so they cannot become independent roots.
    if not isinstance(wrapped_model, FSDP) or not wrapped_model.check_is_root():
        raise RuntimeError('Checkpoint restore requires the root FSDP model')
    state = load_file(str(Path(checkpoint) / 'adapter_model.safetensors'), device='cpu')
    # Older exports retained activation-checkpoint wrapper names.
    clean_state = {key.replace('_checkpoint_wrapped_module.', ''): value for key, value in state.items()}
    if len(clean_state) != len(state):
        raise ValueError('Duplicate adapter keys after removing checkpoint wrappers')
    state = clean_state
    units = []
    for name, module in wrapped_model.named_modules():
        if isinstance(module, FSDP) and ('.lora_A.' in name or '.lora_B.' in name):
            prefix = name.replace('_fsdp_wrapped_module.', '').replace('_checkpoint_wrapped_module.', '').removesuffix('.default')
            units.append((prefix, module))
    loaded = set()
    for name, unit in units:
        with FSDP.summon_full_params(unit, recurse=False, writeback=True, rank0_only=False, offload_to_cpu=False):
            with torch.no_grad():
                for key, param in unit.module.named_parameters(recurse=False):
                    full_key = f'{name}.{key}'
                    if full_key not in state:
                        raise ValueError(f'Missing checkpoint adapter tensor: {full_key}')
                    value = state[full_key]
                    if param.shape != value.shape or not torch.isfinite(value).all():
                        raise ValueError(f'Invalid checkpoint adapter tensor: {full_key}')
                    param.copy_(value)
                    loaded.add(full_key)
    if not loaded or loaded != set(state):
        raise ValueError('Checkpoint adapter keys do not match the wrapped LoRA model')


def export_adapter(trainer, output_dir):
    """All ranks gather small adapter leaves; only rank zero writes the result."""
    state = collect_lora_state(trainer.model_wrapped, trainer.is_world_process_zero())
    if trainer.is_world_process_zero():
        from copy import deepcopy
        from safetensors.torch import save_file
        model = trainer.accelerator.unwrap_model(trainer.model_wrapped)
        config = deepcopy(model.peft_config['default'])
        if str(config.peft_type) not in ('LORA', 'PeftType.LORA') or config.bias != 'none' or config.modules_to_save:
            raise ValueError('Leaf export supports only default LoRA with bias=none and no modules_to_save')
        # PEFT filters supplied keys against wrapped module names, which can silently export zero tensors.
        state = {key.replace('.lora_A.default.', '.lora_A.').replace('.lora_B.default.', '.lora_B.'): value
                 for key, value in state.items()}
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        save_file(state, str(path / 'adapter_model.safetensors'), metadata={'format': 'pt'})
        config.inference_mode = True
        config.save_pretrained(path)
        trainer.processing_class.save_pretrained(output_dir)
    trainer.accelerator.wait_for_everyone()


class AdapterCheckpointMixin:
    """Adapter-only save/resume for the pinned Transformers 4.57.1 Trainer."""

    def save_model(self, output_dir=None, _internal_call=False):
        export_adapter(self, output_dir or self.args.output_dir)

    def _save_optimizer_and_scheduler(self, output_dir):
        import torch
        from accelerate.utils import save_fsdp_optimizer
        # Default Trainer also saves frozen model shards here; keep only optimizer state.
        save_fsdp_optimizer(self.accelerator.state.fsdp_plugin, self.accelerator,
                            self.optimizer, self.model, output_dir)
        if self.args.should_save:
            torch.save(self.lr_scheduler.state_dict(), Path(output_dir) / 'scheduler.pt')

    def _save_checkpoint(self, model, trial):
        from src.coder_training.checkpoints import mark_checkpoint_complete
        path = Path(self._get_output_dir(trial)) / f'checkpoint-{self.state.global_step}'
        if self.is_world_process_zero():
            (path / 'checkpoint_complete.json').unlink(missing_ok=True)
        self.accelerator.wait_for_everyone()
        super()._save_checkpoint(model, trial)
        self.accelerator.wait_for_everyone()
        if self.is_world_process_zero():
            mark_checkpoint_complete(path, self.checkpoint_config_hash, self.args.world_size,
                                     self.accelerator.scaler is not None)
            if getattr(self, 'hub_backup', None) is not None:
                self.hub_backup.submit(path)
        self.accelerator.wait_for_everyone()

    def _load_from_checkpoint(self, resume_from_checkpoint, model=None):
        from src.coder_training.checkpoints import verify_checkpoint
        path = verify_checkpoint(resume_from_checkpoint, self.checkpoint_config_hash,
                                 self.args.world_size)
        load_lora_state(self.model_wrapped if model is None else model, path)
