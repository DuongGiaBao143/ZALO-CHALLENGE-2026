"""Private HF recovery, isolated upload process and portable Kaggle notebook setup."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.upload_hf_adapter import upload, safe_error

ROOT = Path(__file__).resolve().parents[1]


class FakeApi:
    def __init__(self, private=True, missing_remote=False, gated=False):
        self.private = private
        self.missing_remote = missing_remote
        self.gated = gated
        self.calls = []

    def whoami(self):
        return {'name': 'owner'}

    def create_repo(self, **kwargs):
        self.calls.append(('create', kwargs))

    def repo_info(self, *args, **kwargs):
        return SimpleNamespace(private=self.private, gated=self.gated)

    def upload_file(self, **kwargs):
        self.calls.append(('probe', kwargs))

    def upload_folder(self, **kwargs):
        self.calls.append(('upload', kwargs))
        return SimpleNamespace(oid='test-commit')

    def list_repo_files(self, **kwargs):
        self.calls.append(('verify', kwargs))
        return [] if self.missing_remote else ['runs/test/final_adapter/' + name for name in
                                              ['adapter_config.json', 'adapter_model.safetensors']]


def test_preflight_checks_private_repo_and_actual_write():
    api = FakeApi()
    report = upload(api, 'Zalo-challenge', 'runs/test')
    assert report['status'] == 'write_verified' and report['repo_id'] == 'owner/Zalo-challenge'
    assert api.calls[-1][0] == 'probe'
    assert api.calls[0][1]['private'] is True


@pytest.mark.parametrize('gated', [False, 'auto'])
def test_public_destination_is_rejected_without_manual_approval(gated):
    api = FakeApi(private=False, gated=gated)
    with pytest.raises(ValueError, match='manual access approval'):
        upload(api, 'owner/public', 'runs/test')
    assert all(call[0] not in ('upload', 'probe') for call in api.calls)


def test_manual_gated_destination_passes_write_probe():
    api = FakeApi(private=False, gated='manual')
    result = upload(api, 'Crinkk/Zalo-challenge', 'runs/test')
    assert result['status'] == 'write_verified'
    assert api.calls[-1][0] == 'probe'


@pytest.mark.parametrize('missing_remote', [False, True])
def test_final_upload_verifies_both_files_on_committed_revision(tmp_path, missing_remote):
    for name in ['adapter_config.json', 'adapter_model.safetensors']:
        (tmp_path / name).write_bytes(b'adapter')
    api = FakeApi(private=False, gated='manual', missing_remote=missing_remote)
    if missing_remote:
        with pytest.raises(RuntimeError, match='both required files'):
            upload(api, 'owner/private', 'runs/test', tmp_path)
    else:
        result = upload(api, 'owner/private', 'runs/test', tmp_path)
        assert result['status'] == 'uploaded' and result['commit'] == 'test-commit'
        assert api.calls[-1][1]['revision'] == 'test-commit'
        assert next(kwargs for name, kwargs in api.calls if name == 'upload')['ignore_patterns'] == ['README.md']


def test_value_error_is_reported_without_repeated_blind_retries(tmp_path):
    for name in ['adapter_config.json', 'adapter_model.safetensors']:
        (tmp_path / name).write_bytes(b'adapter')
    api = FakeApi()
    attempts = []

    def fail(**kwargs):
        attempts.append(kwargs)
        raise ValueError('invalid upload setting hf_do_not_show')

    api.upload_folder = fail
    with pytest.raises(ValueError) as error:
        upload(api, 'owner/private', 'runs/test', tmp_path)
    assert len(attempts) == 1
    assert safe_error(error.value) == 'invalid upload setting [REDACTED]'


def test_notebooks_are_valid_and_upload_precedes_gpu_evaluation():
    import nbformat
    nb = nbformat.read(ROOT / 'notebooks/Train_Qwen_kaggle.ipynb', as_version=4)
    nbformat.validate(nb)
    code = []
    for cell in nb.cells:
        if cell.cell_type == 'code':
            compile(cell.source, '<kaggle890-cell>', 'exec')
            assert cell.outputs == [] and cell.execution_count is None
            code.append(cell.source)
    full = '\n'.join(code)
    assert 'shop-holdout-v1' in full
    assert "INIT_ADAPTER_DIR = ''" in full and "RESUME_FROM_CHECKPOINT = ''" in full
    assert 'TRAIN_ROWS = 1053' in full
    assert "HF_INPUT_REPO = 'Crinkk/Zalo-challenge'" in full
    assert "HF_REPO_NAME = 'Crinkk/Zalo-challenge'" in full
    assert 'download_verified_bundle(EVAL_BUNDLE_FILE' in full
    assert '/kaggle/input/' not in full
    assert "{'id', 'business_id', 'code'}" in full
    assert "'scripts/build_sft_dataset.py'" in full
    assert full.index('uploaded = run_hf_upload(adapter_to_upload)') < full.index("'vllm==0.10.2'")
    assert "'--no-cache-dir'" in full
    assert 'source.suffix' in full  # ZIP no longer duplicates optimizer checkpoints.

    recovery = nbformat.read(ROOT / 'notebooks/upload_trained_qwen7b_to_hf.ipynb', as_version=4)
    nbformat.validate(recovery)
    source = recovery.cells[1].source
    compile(source, '<recovery-cell>', 'exec')
    assert 'qwen7b_890_fp16_lora/train/final_adapter' in source
    assert 'nvidia-smi' not in source and 'trainer.train(' not in source
    assert 'UPLOAD_SCRIPT' in source and "'-c'" in source and "HF_HUB_OFFLINE='0'" in source


def test_upload_script_starts_online_before_importing_hub(tmp_path):
    import os
    import subprocess
    import sys

    (tmp_path / 'huggingface_hub.py').write_text('''
import os
assert os.environ['HF_HUB_OFFLINE'] == '0'
assert os.environ['TRANSFORMERS_OFFLINE'] == '0'
class HfApi:
    def __init__(self, **kwargs): pass
    def whoami(self): return {'name': 'owner'}
    def create_repo(self, **kwargs): pass
    def repo_info(self, *args, **kwargs):
        return type('Repo', (), {'private': True})()
    def upload_file(self, **kwargs): pass
''', encoding='utf-8')
    env = dict(os.environ, HF_TOKEN='test-token', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               PYTHONPATH=str(tmp_path))
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/upload_hf_adapter.py'),
        '--repo', 'private', '--prefix', 'runs/test', '--report', str(tmp_path / 'report.json')],
        env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'test-token' not in result.stdout + result.stderr
    assert json.loads((tmp_path / 'report.json').read_text())['status'] == 'write_verified'


def test_recovery_cell_only_cleans_staging_and_preserves_adapter_and_checkpoint(tmp_path, monkeypatch):
    import ast
    import subprocess

    notebook = json.loads((ROOT / 'notebooks/upload_trained_qwen7b_to_hf.ipynb').read_text(encoding='utf-8'))
    source = ''.join(notebook['cells'][1]['source'])
    embedded = next(node.value.value for node in ast.parse(source).body if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'UPLOAD_SCRIPT' for t in node.targets))
    assert embedded == (ROOT / 'scripts/upload_hf_adapter.py').read_text(encoding='utf-8')
    working = tmp_path / 'working'
    run = working / 'runs/completed'
    adapter = run / 'train/final_adapter'
    adapter.mkdir(parents=True)
    for name in ['adapter_config.json', 'adapter_model.safetensors']:
        (adapter / name).write_bytes(b'original')
    (run / 'train/completed.json').write_text('{}')
    checkpoint = run / 'train/checkpoint-336'
    checkpoint.mkdir()
    (checkpoint / 'optimizer.bin').write_bytes(b'keep optimizer')
    staging = run / '.train-hub-staging/failed-upload'
    staging.mkdir(parents=True)
    (staging / 'copy.bin').write_bytes(b'temporary')
    source = source.replace(
        "'/kaggle/working/datamate_qwen7b_890/runs/qwen7b_890_fp16_lora/train/final_adapter'", repr(str(adapter)))
    source = source.replace("'/kaggle/working'", repr(str(working)))
    source = source.replace("'/kaggle/working/hf_recovery_upload.json'", repr(str(working / 'report.json')))
    monkeypatch.setenv('HF_TOKEN', 'private-secret')
    calls = []

    def fake_upload(command, **kwargs):
        assert kwargs['env']['HF_HUB_OFFLINE'] == '0' and kwargs['check'] is True
        assert 'private-secret' not in command
        report = Path(command[command.index('--report') + 1])
        report.write_text(json.dumps(dict(status='uploaded', url='https://huggingface.co/owner/private')))
        calls.append(command)

    monkeypatch.setattr(subprocess, 'run', fake_upload)
    exec(compile(source, '<recovery-cell>', 'exec'), {})
    assert len(calls) == 1
    assert not (run / '.train-hub-staging').exists()
    assert (adapter / 'adapter_model.safetensors').read_bytes() == b'original'
    assert (checkpoint / 'optimizer.bin').read_bytes() == b'keep optimizer'
