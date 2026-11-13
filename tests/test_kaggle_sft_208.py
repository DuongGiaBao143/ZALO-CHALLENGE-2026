"""Dataset boundaries, final-turn loss, notebook cells and FSDP adapter resume."""
import ast
import json
import logging
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List

import pytest
import torch

from scripts.train_sft_kaggle_2t4 import inspect_dataset
from src.coder_training.checkpoints import checkpoint_files, mark_checkpoint_complete, resolve_resume_checkpoint
from src.coder_training.fsdp_adapter import completion_loss_inputs

ROOT = Path(__file__).resolve().parents[1]


class Tokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, return_dict):
        assert tokenize and return_dict is False
        text = ''.join(f"<{m['role']}>{m['content']}</>" for m in messages)
        if add_generation_prompt:
            text += '<assistant>'
        return list(text.encode())


def dataset(tmp_path):
    records = []
    for n, turns in enumerate((1, 2)):
        records.append(dict(id=f'q{n}', business_id='biz1', prompt_format='folder_readme_schema_v1',
            messages=[dict(role='system', content='system')] +
            [dict(role=role, content=content) for role,content in
             [('user','question'), ('assistant','bad-code'), ('user','error'), ('assistant','fixed-code')][:2*turns]]))
    path = tmp_path / 'sft.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in records), encoding='utf-8')
    return path, records


def test_preflight_keeps_multiturn_and_reports_overlength_without_truncation(tmp_path):
    path, records = dataset(tmp_path)
    report = inspect_dataset(path, Tokenizer(), max_seq_len=1, expected_rows=2)
    assert report['records'] == 2 and len(report['overlength']) == 2
    assert report['lengths'][1]['messages'] == 5
    assert json.loads(path.read_text().splitlines()[1]) == records[1]
    with pytest.raises(ValueError, match='Expected 208'):
        inspect_dataset(path, Tokenizer(), max_seq_len=1000, expected_rows=208)
    with path.open('a') as stream:
        stream.write('\n' + json.dumps(records[0]))
    with pytest.raises(ValueError, match='Duplicate'):
        inspect_dataset(path, Tokenizer(), max_seq_len=1000, expected_rows=3)


def test_preflight_rejects_old_prompt_format(tmp_path):
    path, records = dataset(tmp_path)
    records[0].pop('prompt_format')
    path.write_text('\n'.join(json.dumps(r) for r in records))
    with pytest.raises(ValueError, match='Invalid new-pipeline'):
        inspect_dataset(path, Tokenizer(), 1000, expected_rows=2)


def test_existing_preprocessor_masks_failed_assistant_turn(tmp_path):
    path, records = dataset(tmp_path)
    tree = ast.parse((ROOT / 'scripts/train_sft_lora.py').read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))
             and n.name in {'DataMateDataset', 'prepare_dataset'}]
    namespace = dict(torch=torch, json=json, logger=logging.getLogger(__name__), Any=Any, Dict=Dict, List=List)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<existing-preprocessor>', 'exec'), namespace)
    tokenizer = Tokenizer()
    samples = namespace['prepare_dataset'](str(path), tokenizer, 1000)
    prompt_length = len(tokenizer.apply_chat_template(records[1]['messages'][:-1], tokenize=True,
                        add_generation_prompt=True, return_dict=False))
    assert samples[1]['labels'][:prompt_length] == [-100] * prompt_length
    assert bytes(samples[1]['labels'][prompt_length:]).decode() == 'fixed-code</>'


def test_checkpoint_latest_ignores_partial_and_rejects_changed_state(tmp_path):
    for step in (1, 10):
        path = tmp_path / f'checkpoint-{step}'
        path.mkdir()
        for filename in checkpoint_files():
            (path / filename).write_bytes(b'state')
        (path / 'trainer_state.json').write_text(json.dumps(dict(global_step=step)))
        mark_checkpoint_complete(path, 'same')
    (tmp_path / 'checkpoint-20').mkdir()
    assert resolve_resume_checkpoint('latest', tmp_path, 'same') == tmp_path / 'checkpoint-10'
    with pytest.raises(ValueError, match='mismatch'):
        resolve_resume_checkpoint('latest', tmp_path, 'changed')
    (tmp_path / 'checkpoint-10/optimizer.bin').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='checksum'):
        resolve_resume_checkpoint('latest', tmp_path, 'same')


def test_kaggle_notebook_cells_compile_and_use_two_rank_launch():
    nb = json.loads((ROOT / 'notebooks/02_train_sft_qwen7b_kaggle_2t4_208.ipynb').read_text(encoding='utf-8'))
    import nbformat
    nbformat.validate(nbformat.from_dict(nb))
    source = []
    for cell in nb['cells']:
        if cell['cell_type'] == 'code':
            text = ''.join(cell['source'])
            compile(text, '<kaggle-cell>', 'exec')
            assert cell['outputs'] == [] and cell['execution_count'] is None
            source.append(text)
    text = '\n'.join(source)
    assert 'accelerate.commands.launch' in text
    assert '--smoke' in text and 'checkpoint_restore_checked' in text
    assert 'cfa70a9af1b87d282ff5428c7bf7afd9a3308a449a2095d23b320479284fd8fc' in text
    assert 'drive.mount' not in text


def test_completion_logits_match_full_qwen_loss_and_gradients(monkeypatch):
    monkeypatch.setenv('USE_TF', '0')
    pytest.importorskip('transformers')
    from transformers import Qwen2Config, Qwen2ForCausalLM
    torch.manual_seed(42)
    model = Qwen2ForCausalLM(Qwen2Config(vocab_size=32, hidden_size=16, intermediate_size=32,
        num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1, use_cache=False))
    inputs = dict(input_ids=torch.tensor([[1,2,3,4,5],[2,3,4,5,0]]),
                  labels=torch.tensor([[-100,-100,-100,4,5],[-100,-100,4,5,-100]]))
    model.eval()
    full = model(**inputs).loss
    full.backward()
    gradients = {n:p.grad.clone() for n,p in model.named_parameters() if p.grad is not None}
    model.zero_grad(set_to_none=True)
    small = model(**completion_loss_inputs(inputs)).loss
    small.backward()
    torch.testing.assert_close(small, full)
    for name, p in model.named_parameters():
        if name in gradients:
            torch.testing.assert_close(p.grad, gradients[name], atol=1e-6, rtol=1e-5)


@pytest.mark.parametrize('split_vocabulary', [False, True])
def test_tiny_fsdp_adapter_optimizer_roundtrip(tmp_path, split_vocabulary):
    pytest.importorskip('peft')
    # Isolate the process group and FSDP state from other tests.
    script = r'''
import json, sys
from pathlib import Path
from types import SimpleNamespace
import torch
import torch.distributed as dist
from functools import partial
from torch.distributed.algorithms._checkpoint.checkpoint_wrapper import (
    CheckpointImpl, apply_activation_checkpointing, checkpoint_wrapper)
from torch.distributed.fsdp import FullyShardedDataParallel as FSDP, StateDictType, FullStateDictConfig, FullOptimStateDictConfig, MixedPrecision
from transformers import Qwen2Config, Qwen2ForCausalLM
from peft import LoraConfig, get_peft_model
from peft.utils.other import fsdp_auto_wrap_policy
from accelerate.utils import load_fsdp_optimizer
from accelerate.state import PartialState
from src.coder_training.fsdp_adapter import collect_lora_state, load_lora_state
from src.coder_training.fsdp_adapter import AdapterCheckpointMixin, export_adapter, prepare_fsdp_qlora_model
from src.coder_training.checkpoints import mark_checkpoint_complete, verify_checkpoint

root = Path(sys.argv[1]).resolve()
PartialState(cpu=True)
dist.init_process_group('gloo', init_method=(root / 'rendezvous').as_uri(), rank=0, world_size=1)
plugin = SimpleNamespace(fsdp_version=1, state_dict_type=StateDictType.FULL_STATE_DICT,
                         state_dict_config=FullStateDictConfig(offload_to_cpu=False, rank0_only=False),
                         optim_state_dict_config=FullOptimStateDictConfig(offload_to_cpu=False, rank0_only=False))
accel = SimpleNamespace(process_index=0, state=SimpleNamespace(fsdp_plugin=plugin), is_fsdp2=False,
                         wait_for_everyone=lambda: None, unwrap_model=lambda m: m.module)
def build():
    torch.manual_seed(7)
    model = get_peft_model(Qwen2ForCausalLM(Qwen2Config(vocab_size=32, hidden_size=16, intermediate_size=32,
        num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1, use_cache=False)),
        LoraConfig(task_type='CAUSAL_LM', r=2, lora_alpha=4, target_modules=['q_proj', 'v_proj'], lora_dropout=0))
    policy = fsdp_auto_wrap_policy(model)
    mixed_precision = None
    if SPLIT_VOCABULARY:
        policy = prepare_fsdp_qlora_model(model)
        assert model.get_input_embeddings().weight.dtype == torch.float16
        assert model.get_output_embeddings().weight.dtype == torch.float16
        assert all(p.dtype == torch.float32 for n,p in model.named_parameters() if 'lora_' in n)
        # Transformers 4.57.1 resets the policy immediately before accelerator.prepare().
        import ast
        class BaseTrainer:
            def _fsdp_qlora_plugin_updates(self):
                self.accelerator.state.fsdp_plugin.auto_wrap_policy = fsdp_auto_wrap_policy(self.model)
                self.accelerator.state.fsdp_plugin.mixed_precision_policy = 'nf4-float32-storage'
        tree = ast.parse(Path('scripts/train_sft_kaggle_2t4.py').read_text(encoding='utf-8'))
        trainer_class = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == 'CompletionTrainer')
        namespace = dict(Trainer=BaseTrainer, AdapterCheckpointMixin=AdapterCheckpointMixin,
            args=SimpleNamespace(load_in_4bit=True), prepare_fsdp_qlora_model=prepare_fsdp_qlora_model)
        exec(compile(ast.Module(body=[trainer_class], type_ignores=[]), '<actual-completion-trainer>', 'exec'), namespace)
        trainer = namespace['CompletionTrainer']()
        trainer.model = model
        training_plugin = SimpleNamespace(auto_wrap_policy=policy)
        trainer.accelerator = SimpleNamespace(state=SimpleNamespace(fsdp_plugin=training_plugin))
        trainer._fsdp_qlora_plugin_updates()
        assert training_plugin.mixed_precision_policy == 'nf4-float32-storage'
        policy = training_plugin.auto_wrap_policy
        mixed_precision = MixedPrecision(param_dtype=torch.float32, reduce_dtype=torch.float32,
                                         buffer_dtype=torch.float32)
        from peft.tuners.lora import LoraLayer
        for module in model.modules():
            if isinstance(module, LoraLayer):
                module.cast_input_dtype_enabled = False
    wrapped = FSDP(model, auto_wrap_policy=policy, device_id=torch.device('cpu'),
                   use_orig_params=False, mixed_precision=mixed_precision)
    if SPLIT_VOCABULARY:
        assert isinstance(wrapped.module.get_input_embeddings(), FSDP)
        assert isinstance(wrapped.module.get_output_embeddings(), FSDP)
    apply_activation_checkpointing(wrapped,
        checkpoint_wrapper_fn=partial(checkpoint_wrapper, checkpoint_impl=CheckpointImpl.NO_REENTRANT),
        auto_wrap_policy=fsdp_auto_wrap_policy(model))
    optimizer = torch.optim.AdamW([p for p in wrapped.parameters() if p.requires_grad], lr=0.01)
    return wrapped, optimizer, torch.optim.lr_scheduler.LambdaLR(optimizer, lambda n: 1 / (n + 1))
def step(model, optimizer, scheduler):
    optimizer.zero_grad(set_to_none=True)
    ids = torch.tensor([[1, 2, 3, 4]])
    loss = model(input_ids=ids, labels=ids).loss
    loss.backward()
    optimizer.step()
    scheduler.step()
    return loss.detach()
class Harness(AdapterCheckpointMixin):
    pass
class Tokenizer:
    def save_pretrained(self, path):
        pass
try:
    model, optimizer, scheduler = build()
    step(model, optimizer, scheduler)
    checkpoint = root / 'checkpoint-1'
    h = Harness()
    h.accelerator, h.model, h.model_wrapped = accel, model, model
    h.optimizer, h.lr_scheduler = optimizer, scheduler
    h.is_fsdp_enabled = True
    h.is_world_process_zero = lambda: True
    h.args = SimpleNamespace(should_save=True, world_size=1)
    h.checkpoint_config_hash = 'test'
    h.processing_class = Tokenizer()
    export_adapter(h, checkpoint)
    from safetensors.torch import load_file
    from peft import PeftModel, get_peft_model_state_dict
    saved = load_file(checkpoint / 'adapter_model.safetensors')
    assert saved and not any('_checkpoint_wrapped_module' in key or '_fsdp_wrapped_module' in key for key in saved)
    plain = PeftModel.from_pretrained(Qwen2ForCausalLM(Qwen2Config(vocab_size=32, hidden_size=16,
        intermediate_size=32, num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1,
        use_cache=False)), checkpoint, local_files_only=True)
    plain_state = get_peft_model_state_dict(plain)
    assert plain_state.keys() == saved.keys()
    for key in saved:
        torch.testing.assert_close(plain_state[key], saved[key], rtol=0, atol=0)
    h._save_optimizer_and_scheduler(checkpoint)
    torch.save({'test': True}, checkpoint / 'rng_state.pth')
    (checkpoint / 'trainer_state.json').write_text(json.dumps(dict(global_step=1)))
    mark_checkpoint_complete(checkpoint, 'test', world_size=1, has_scaler=False)
    verify_checkpoint(checkpoint, 'test', world_size=1)
    assert not (checkpoint / 'pytorch_model_fsdp.bin').exists()
    expected_loss = step(model, optimizer, scheduler)
    expected = collect_lora_state(model, True)
    restored, restored_opt, restored_sched = build()
    h.model, h.model_wrapped = restored, restored
    h._load_from_checkpoint(checkpoint, restored)
    load_fsdp_optimizer(plugin, accel, restored_opt, restored, checkpoint)
    restored_sched.load_state_dict(torch.load(checkpoint / 'scheduler.pt', weights_only=True))
    torch.testing.assert_close(step(restored, restored_opt, restored_sched), expected_loss)
    actual = collect_lora_state(restored, True)
    assert expected.keys() == actual.keys()
    for name in expected:
        torch.testing.assert_close(actual[name], expected[name])
    assert restored_sched.get_last_lr() == scheduler.get_last_lr()
    print('Tiny CPU FSDP adapter + optimizer + scheduler resume matches uninterrupted next step')
finally:
    dist.destroy_process_group()
'''
    script = script.replace('SPLIT_VOCABULARY', repr(split_vocabulary))
    subprocess.run([sys.executable, '-c', script, str(tmp_path)], check=True, timeout=120)
