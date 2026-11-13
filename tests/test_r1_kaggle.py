import json
from pathlib import Path
from types import SimpleNamespace
import sys

import nbformat
import pytest

from scripts.train_sft_kaggle_2t4 import inspect_dataset

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'notebooks/Train_DeepSeek_R1_14B_code_only_Kaggle_2T4.ipynb'


def test_r1_fsdp_preflight_uses_closing_think_target_and_reports_full_lengths(tmp_path):
    class R1Tokenizer:
        eos_token_id = 0

        def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, return_dict=None):
            assert add_generation_prompt
            return [1, 2, 3] if tokenize else '<Assistant><think>\n'

        def encode(self, text, *, add_special_tokens):
            assert not add_special_tokens
            return list(text.encode())
    rows = [dict(id='q1', business_id='train_shop', prompt_format='folder_readme_schema_v1',
                 messages=[dict(role='system', content='system'), dict(role='user', content='question'),
                           dict(role='assistant', content='```python\nprint(1)\n```')])]
    path = tmp_path / 'train.jsonl'
    path.write_text(json.dumps(rows[0]))
    before = path.read_bytes()
    report = inspect_dataset(path, R1Tokenizer(), 10, completion_format='r1-code-only')
    expected = len('</think>\n```python\nprint(1)\n```') + 1
    assert report['records'] == 1
    assert report['lengths'][0]['final_tokens'] == expected
    assert report['max_tokens'] == expected + 3
    assert report['overlength'] == report['lengths']
    assert path.read_bytes() == before


def test_kaggle_notebook_compiles_and_smoke_gates_training_and_upload():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    nbformat.validate(notebook)
    for cell in notebook.cells:
        if cell.cell_type == 'code':
            compile(cell.source, cell.id, 'exec')
            assert cell.outputs == [] and cell.execution_count is None
    code = '\n'.join(c.source for c in notebook.cells if c.cell_type == 'code')
    assert "'--load-in-4bit', '--completion-format', 'r1-code-only'" in code
    assert "'--data', str(INPUT / 'training/train.jsonl')" in code
    assert "'data/train/answers.jsonl'" not in code
    assert code.index("smoke['checkpoint_restore_checked']") < code.index("RUN_ROOT / 'train.log'")
    assert code.index("RUN_ROOT / 'train.log'") < code.index("'--adapter-dir'")
    assert "HF_HUB_OFFLINE='0' if online or backup else '1'" in code
    assert 'bnb_4bit_quant_storage=torch.float32' in (ROOT / 'scripts/train_sft_kaggle_2t4.py').read_text()


@pytest.mark.parametrize('corrupt', [False, True])
def test_final_upload_is_not_reported_verified_until_download_hash_matches(tmp_path, monkeypatch, corrupt):
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    cell = notebook.cells[-1].source
    adapter = tmp_path / 'adapter'
    adapter.mkdir()
    names = ['adapter_model.safetensors', 'adapter_config.json']
    for name in names:
        (adapter / name).write_bytes(b'fixture adapter')
    remote = tmp_path / 'download'
    remote.mkdir()
    for name in names:
        (remote / name).write_bytes(b'corrupt' if corrupt else (adapter / name).read_bytes())
    uploads = []
    downloads = []
    result = dict(status='uploaded', path_in_repo='runs/test/final_adapter',
                  commit='a'*40, url='https://huggingface.co/owner/private/tree/main/runs/test/final_adapter')

    def run_logged(command, log, online=False):
        assert online and '--adapter-dir' in command
        (tmp_path / 'hf_upload.json').write_text(json.dumps(result))

    def download(**kwargs):
        downloads.append(kwargs)
        assert kwargs['revision'] == result['commit']
        return str(remote / kwargs['filename'].split('/')[-1])

    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(HfApi=lambda **kw: SimpleNamespace(
        repo_info=lambda *a, **kw: SimpleNamespace(private=True),
        upload_folder=lambda **kwargs: uploads.append(kwargs))))
    ns = dict(Path=Path, json=json, hashlib=__import__('hashlib'), RUN_ROOT=tmp_path, REMOTE_PREFIX='runs/test',
              sys=sys, run_logged=run_logged, HF_REPO='owner/private', HF_TOKEN='fixture-secret',
              ADAPTER=adapter, RUN_NAME='test', hf_hub_download=download)
    if corrupt:
        with pytest.raises(RuntimeError, match='hash mismatch'):
            exec(cell, ns)
        assert not json.loads((tmp_path / 'hf_upload.json').read_text()).get('download_verified')
        assert not uploads
    else:
        exec(cell, ns)
        assert json.loads((tmp_path / 'hf_upload.json').read_text())['download_verified']
        assert len(downloads) == 2 and len(uploads) == 1


@pytest.mark.parametrize('revision', ['original', 'patched', 'unknown'])
def test_in_session_dtype_hotfix_preserves_weights_and_failed_smoke(tmp_path, revision):
    import ast
    source = (ROOT / 'scripts/kaggle_r1_dtype_hotfix.py').read_text(encoding='utf-8')
    patched_trainer = (ROOT / 'scripts/train_sft_kaggle_2t4.py').read_bytes()
    patch = next(ast.literal_eval(n.value) for n in ast.walk(ast.parse(source))
                 if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'patch' for t in n.targets))
    original_trainer = patched_trainer.decode().replace(patch, '').encode()
    trainer = tmp_path / 'input/scripts/train_sft_kaggle_2t4.py'
    trainer.parent.mkdir(parents=True)
    initial = {'original': original_trainer, 'patched': patched_trainer, 'unknown': b'unknown trainer'}[revision]
    trainer.write_bytes(initial)
    weights = tmp_path / 'downloaded_weights.safetensors'
    weights.write_bytes(b'existing model checkpoint')
    run = tmp_path / 'run'
    (run / 'smoke').mkdir(parents=True)
    old_smoke = run / 'smoke/failed.log'
    old_smoke.write_text('previous dtype error')
    calls = []

    def run_logged(command, log):
        calls.append(command)
        output = Path(command[command.index('--output-dir') + 1])
        assert output != run / 'smoke' and command[command.index('--grad-accum') + 1] == '1'
        output.mkdir()
        (output / 'completed.json').write_text(json.dumps(dict(status='passed', checkpoint_restore_checked=True,
            ranks=[dict(rank=rank, steps=2, loss=0.5, peak_vram_gib=1) for rank in (0, 1)])))

    ns = dict(INPUT=trainer.parents[1], RUN_ROOT=run, BASE_ARGS=['--grad-accum', '8'],
              LAUNCH=['python', str(trainer)], run_logged=run_logged)
    if revision == 'unknown':
        with pytest.raises(ValueError, match='Unexpected trainer'):
            exec(source, ns)
        assert trainer.read_bytes() == initial and not calls
    else:
        exec(source, ns)
        assert trainer.read_bytes() == patched_trainer
        assert len(calls) == 1 and ns['BASE_ARGS'] == ['--grad-accum', '8']
    assert weights.read_bytes() == b'existing model checkpoint'
    assert old_smoke.read_text() == 'previous dtype error'
