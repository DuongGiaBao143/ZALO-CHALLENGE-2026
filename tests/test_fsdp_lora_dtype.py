"""Keep LoRA dropout precision stable when FSDP changes adapter weight views."""
import ast
import json
from pathlib import Path

import pytest
import torch
from peft import LoraConfig, get_peft_model
from peft.tuners.lora import LoraLayer
from torch.utils.checkpoint import CheckpointError, checkpoint


def run_layer(checkpointed, patched):
    torch.manual_seed(42)
    model = get_peft_model(
        torch.nn.Sequential(torch.nn.Linear(8, 8, bias=False, dtype=torch.float16)),
        LoraConfig(target_modules=['0'], r=2, lora_alpha=4, lora_dropout=0.25),
    )
    layer = model.base_model.model[0]
    torch.nn.init.normal_(layer.lora_B['default'].weight)
    if patched:
        tree = ast.parse((Path(__file__).resolve().parents[1] /
                          'scripts/train_sft_kaggle_2t4.py').read_text(encoding='utf-8'))
        run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run')
        configure = next(node for node in run.body if isinstance(node, ast.For)
                         and 'cast_input_dtype_enabled' in ast.unparse(node))
        exec(compile(ast.Module(body=[configure], type_ignores=[]), '<training-dtype-setup>', 'exec'),
             dict(model=model, LoraLayer=LoraLayer))
    inputs = torch.randn(2, 4, 8, dtype=torch.float16, requires_grad=True)
    with torch.autocast('cpu', dtype=torch.float16):
        output = checkpoint(model, inputs, use_reentrant=False) if checkpointed else model(inputs)
        loss = output.float().square().mean()
    # FSDP exposes FP32 master views before forward and FP16 compute views before recompute.
    for leaf in (layer.lora_A['default'], layer.lora_B['default']):
        leaf.weight.data = leaf.weight.data.half()
    loss.backward()
    return loss.detach(), inputs.grad, {
        name: param.grad for name, param in model.named_parameters() if param.requires_grad
    }


def test_fsdp_weight_view_change_keeps_checkpoint_loss_and_gradients():
    with pytest.raises(CheckpointError, match='different metadata'):
        run_layer(checkpointed=True, patched=False)
    expected = run_layer(checkpointed=False, patched=True)
    actual = run_layer(checkpointed=True, patched=True)
    torch.testing.assert_close(actual[0], expected[0])
    torch.testing.assert_close(actual[1], expected[1])
    assert actual[2].keys() == expected[2].keys()
    for name in expected[2]:
        assert actual[2][name] is not None and torch.isfinite(actual[2][name]).all()
        torch.testing.assert_close(actual[2][name], expected[2][name])


def test_notebook_hotfix_patches_old_bundle_once(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    source = (root / 'scripts/train_sft_kaggle_2t4.py').read_text(encoding='utf-8')
    source = source.replace('    from peft.tuners.lora import LoraLayer\n', '')
    start = source.index('    # FSDP changes weight views')
    end = source.index('    if main:\n        model.print_trainable_parameters()', start)
    source = source[:start] + source[end:]
    script = tmp_path / 'scripts/train_sft_kaggle_2t4.py'
    script.parent.mkdir()
    script.write_text(source, encoding='utf-8')
    notebook = json.loads((root / 'notebooks/02_train_sft_qwen7b_kaggle_2t4_890.ipynb')
                          .read_text(encoding='utf-8'))
    smoke = next(''.join(c['source']) for c in notebook['cells']
                 if c['cell_type'] == 'code' and 'LAUNCH = ' in ''.join(c['source']))
    hotfix = smoke.split('LAUNCH = ')[0]
    monkeypatch.chdir(tmp_path)
    exec(hotfix, {})
    patched = script.read_text(encoding='utf-8')
    compile(patched, str(script), 'exec')
    assert 'module.cast_input_dtype_enabled = False' in patched
    assert "'activation_checkpointing': True" in patched
    exec(hotfix, {})
    assert script.read_text(encoding='utf-8') == patched
