from pathlib import Path
import subprocess
import sys
import nbformat
import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = ROOT / "notebooks/Train_DeepSeek_R1_14B_Reasoning_Kaggle_2T4.ipynb"
TRAINER_PATH = ROOT / "scripts/train_sft_kaggle_2t4_reasoning.py"


def test_kaggle_reasoning_notebook_compiles_and_uses_optimal_vram_settings():
    assert NOTEBOOK_PATH.is_file(), f"Notebook not found: {NOTEBOOK_PATH}"
    nb = nbformat.read(str(NOTEBOOK_PATH), as_version=4)
    nbformat.validate(nb)

    code_cells = []
    for idx, cell in enumerate(nb.cells):
        if cell.cell_type == "code":
            code_cells.append(cell.source)
            compile(cell.source, f"<cell {idx}>", "exec")
            assert cell.outputs == []
            assert cell.execution_count is None

    all_code = "\n".join(code_cells)

    # 1. Context cap to 2560 tokens for 15GB T4 VRAM headroom
    assert "MAX_SEQ_LEN = 2560" in all_code

    # 2. Defragmentation config
    assert "expandable_segments:True,max_split_size_mb:128" in all_code

    # 3. Model & Completion Format
    assert "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B" in all_code
    assert "'--completion-format', 'r1-reasoning'" in all_code


def test_trainer_script_has_safe_ac_and_fp16_vocab_unshard(tmp_path):
    text = TRAINER_PATH.read_text(encoding="utf-8")
    assert "safe_apply_ac" in text
    assert "m.__class__.__name__ == 'Qwen2DecoderLayer'" in text
    assert "param_dtype=None, reduce_dtype=torch.float32, buffer_dtype=torch.float32" in text
    assert "torch.cuda.empty_cache()" in text
    assert "default=2560" in text

    script = r'''
import sys
from pathlib import Path
from functools import partial
import torch
import torch.distributed as dist
from torch.distributed.algorithms._checkpoint.checkpoint_wrapper import (
    CheckpointImpl, CheckpointWrapper, apply_activation_checkpointing, checkpoint_wrapper
)
from torch.distributed.fsdp import FullyShardedDataParallel as FSDP, MixedPrecision
from transformers import Qwen2Config, Qwen2ForCausalLM
from peft import LoraConfig, get_peft_model
from peft.tuners.lora import LoraLayer
from accelerate.state import PartialState
from src.coder_training.fsdp_adapter import collect_lora_state, prepare_fsdp_qlora_model

root = Path(sys.argv[1]).resolve()
PartialState(cpu=True)
dist.init_process_group('gloo', init_method=(root / 'rendezvous').as_uri(), rank=0, world_size=1)
try:
    torch.manual_seed(42)
    base = Qwen2ForCausalLM(Qwen2Config(
        vocab_size=64, hidden_size=16, intermediate_size=32,
        num_hidden_layers=2, num_attention_heads=2, num_key_value_heads=1,
        tie_word_embeddings=False, use_cache=False
    ))
    base.enable_input_require_grads()
    model = get_peft_model(base, LoraConfig(
        task_type='CAUSAL_LM', r=2, lora_alpha=4,
        target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj'],
        lora_dropout=0.0
    ))
    for m in model.modules():
        if isinstance(m, LoraLayer):
            m.cast_input_dtype_enabled = False

    policy = prepare_fsdp_qlora_model(model)
    mp = MixedPrecision(param_dtype=None, reduce_dtype=torch.float32, buffer_dtype=torch.float32)
    wrapped = FSDP(model, auto_wrap_policy=policy, device_id=torch.device('cpu'),
                   use_orig_params=False, mixed_precision=mp)

    # Apply the exact safe_apply_ac logic from train_sft_kaggle_2t4_reasoning.py
    apply_activation_checkpointing(
        wrapped,
        checkpoint_wrapper_fn=partial(checkpoint_wrapper, checkpoint_impl=CheckpointImpl.NO_REENTRANT),
        check_fn=lambda m: m.__class__.__name__ == 'Qwen2DecoderLayer',
        auto_wrap_policy=None,
    )

    # 1. Verify Qwen2DecoderLayer is wrapped in CheckpointWrapper, while lm_head/embed_tokens are NOT
    checkpointed = [name for name, m in wrapped.named_modules() if isinstance(m, CheckpointWrapper)]
    assert len(checkpointed) == 2, f"Expected 2 checkpointed decoder layers, got {checkpointed}"
    assert not any('lm_head' in n or 'embed_tokens' in n or 'lora_' in n for n in checkpointed)

    # 2. Run forward + backward under FP16 autocast to trigger lazy_init and verify unshard dtypes
    ids = torch.tensor([[1, 2, 3, 4]])
    with torch.autocast('cpu', dtype=torch.float16):
        loss = wrapped(input_ids=ids, labels=ids).loss
    loss.backward()

    # 3. Verify lm_head and embed_tokens stay in FP16 during unshard (no 2.90 GiB FP32 upcast!)
    for vocab_fsdp in (wrapped.module.get_input_embeddings(), wrapped.module.get_output_embeddings()):
        assert isinstance(vocab_fsdp, FSDP)
        handle = vocab_fsdp._handle
        assert handle._orig_param_dtype == torch.float16
        assert handle._fwd_bwd_param_dtype == torch.float16
        assert not handle._uses_param_mixed_precision
        assert not hasattr(vocab_fsdp._flat_param, '_mp_shard')

    # 4. Verify frozen decoder layer base weights stay in FP32 (preserving NF4 quant_storage)
    layer0_fsdp = wrapped.module.base_model.model.model.layers[0]
    assert isinstance(layer0_fsdp, FSDP)
    assert layer0_fsdp._handle._orig_param_dtype == torch.float32
    assert layer0_fsdp._handle._fwd_bwd_param_dtype == torch.float32

    # 5. Verify LoRA adapter collection succeeds cleanly
    state = collect_lora_state(wrapped, True)
    assert len(state) == 2 * 7 * 2
    assert all(torch.isfinite(v).all() for v in state.values())
finally:
    dist.destroy_process_group()
'''
    subprocess.run([sys.executable, '-c', script, str(tmp_path)], check=True, timeout=120)
