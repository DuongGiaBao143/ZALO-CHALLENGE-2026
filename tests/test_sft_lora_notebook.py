"""Check notebook setup and propagation of a failed training process without a GPU."""

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def notebook_cell(marker):
    notebook = json.loads(
        (ROOT / 'notebooks/02_train_sft_qwen7b_lora.ipynb').read_text(encoding='utf-8')
    )
    return next(''.join(cell['source']) for cell in notebook['cells']
                if cell['cell_type'] == 'code' and marker in ''.join(cell['source']))


def test_setup_checks_lora_after_removing_optional_torchao(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, 'run', lambda args, **kwargs: calls.append((args, kwargs)))
    exec(compile(notebook_cell("'pip', 'install'"), '<setup-cell>', 'exec'), {})
    assert all(kwargs.get('check') is True for _, kwargs in calls)
    assert calls[1][0][-3:] == ['uninstall', '-y', 'torchao']
    smoke = calls[2][0][-1]
    assert 'get_peft_model(' in smoke and 'lora_' in smoke
    compile(smoke, '<lora-check>', 'exec')


@pytest.mark.parametrize('exit_code', [0, 3])
def test_training_cell_only_reports_success_for_zero_exit(tmp_path, monkeypatch, capsys, exit_code):
    drive = tmp_path / 'drive'
    (drive / 'scripts').mkdir(parents=True)
    (drive / 'scripts/train_sft_lora.py').write_text(
        'import sys\nprint("training output", flush=True)\n'
        'print("original error detail", file=sys.stderr, flush=True)\n'
        f'sys.exit({exit_code})\n', encoding='utf-8'
    )
    work = tmp_path / 'work'
    (work / 'scripts').mkdir(parents=True)
    monkeypatch.chdir(work)
    source = notebook_cell("'--lora_alpha'")
    if exit_code:
        with pytest.raises(RuntimeError, match=f'exit {exit_code}') as failure:
            exec(compile(source, '<train-cell>', 'exec'), {'gdrive_project': str(drive)})
        assert 'original error detail' in str(failure.value)
        output = capsys.readouterr().out
        assert 'original error detail' in output
        assert 'Huấn luyện hoàn thành' not in output
    else:
        exec(compile(source, '<train-cell>', 'exec'), {'gdrive_project': str(drive)})
        assert 'Huấn luyện hoàn thành' in capsys.readouterr().out
    log = (work / 'result/sft_adapter_qwen7b/train.log').read_text(encoding='utf-8')
    assert 'training output' in log and 'original error detail' in log


@pytest.mark.parametrize('exit_code', [0, 5])
def test_evaluation_uses_cached_base_and_stops_before_scoring_on_failure(tmp_path, monkeypatch, exit_code):
    import yaml

    monkeypatch.chdir(tmp_path)
    (tmp_path / 'configs').mkdir()
    baseline = tmp_path / 'configs/baseline_7b_a100.yaml'
    original = 'model:\n  local_model_dir: /workspace/missing\npaths: {}\n'
    baseline.write_text(original, encoding='utf-8')
    adapter = tmp_path / 'result/sft_adapter_qwen7b/final_adapter'
    adapter.mkdir(parents=True)
    (adapter / 'adapter_config.json').write_text(
        json.dumps({'base_model_name_or_path': 'Qwen/Qwen2.5-Coder-7B-Instruct'}), encoding='utf-8'
    )
    cached_model = tmp_path / 'cached_snapshot'
    cached_model.mkdir()
    (cached_model / 'config.json').write_text('{}', encoding='utf-8')
    (cached_model / 'model.safetensors').write_bytes(b'cached weights')
    calls = []

    def hf_hub_download(**kwargs):
        calls.append(kwargs)
        return str(cached_model / 'config.json')

    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(hf_hub_download=hf_hub_download))
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/run_inference.py').write_text(
        f'import sys\nprint("inference detail", flush=True)\nsys.exit({exit_code})\n', encoding='utf-8'
    )
    (tmp_path / 'scripts/evaluate_local.py').write_text(
        'from pathlib import Path\nPath("scored").touch()\n', encoding='utf-8'
    )
    source = notebook_cell("cfg_path = Path('result/sft_7b_pilot/config.yaml')")
    if exit_code:
        with pytest.raises(RuntimeError, match='inference detail'):
            exec(compile(source, '<eval-cell>', 'exec'), {})
    else:
        exec(compile(source, '<eval-cell>', 'exec'), {})
    assert (tmp_path / 'scored').exists() is (exit_code == 0)
    assert calls == [{'repo_id': 'Qwen/Qwen2.5-Coder-7B-Instruct', 'filename': 'config.json', 'local_files_only': True}]
    config = yaml.safe_load((tmp_path / 'result/sft_7b_pilot/config.yaml').read_text(encoding='utf-8'))
    model_path = tmp_path / 'tmp/sft_base_model'
    assert config['model']['local_model_dir'] == str(model_path)
    assert (model_path / 'model.safetensors').read_bytes() == b'cached weights'
    assert not (model_path / 'model.safetensors').is_symlink()
    assert not (model_path / 'README.md').exists()
    assert config['model']['adapter_path'] == str(adapter)
    assert baseline.read_text(encoding='utf-8') == original
