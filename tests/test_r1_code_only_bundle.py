import json
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
from zipfile import ZipFile

import nbformat
import pytest

from scripts.package_r1_code_only import package
from src.coder_training.io_utils import file_hash

ROOT = Path(__file__).resolve().parents[1]


def test_bundle_filters_whole_dev_shops_and_keeps_raw_inputs_unchanged(tmp_path):
    split = tmp_path / 'raw'
    for shop in ('train_shop', 'dev_shop'):
        directory = split / 'data' / shop
        directory.mkdir(parents=True)
        (directory / 'sales.csv').write_text('value\n1\n')
    (split / 'rulebook.md').write_text('Use sales.csv')
    (split / 'calendar.csv').write_text('date\n2026-01-01\n')
    records = [dict(id=qid, business_id=shop, question='Count rows?', as_of_date='2026-01-01')
               for qid, shop in [('train_q', 'train_shop'), ('dev_q', 'dev_shop'), ('same_shop_q', 'dev_shop')]]
    (split / 'questions.jsonl').write_text('\n'.join(map(json.dumps, records)))
    (split / 'answers.jsonl').write_text('\n'.join(json.dumps(dict(id=r['id'], type='number', answer=1)) for r in records))
    dataset = tmp_path / 'codes.jsonl'
    dataset.write_text('\n'.join(json.dumps(dict(id=r['id'], business_id=r['business_id'], code='print(1)')) for r in records))
    selection = tmp_path / 'selection.json'
    selection.write_text(json.dumps(dict(question_ids=['dev_q'])))
    hashes = {p: file_hash(p) for p in split.rglob('*') if p.is_file()}
    archive = package(dataset, selection, split, tmp_path / 'output')
    assert hashes == {p: file_hash(p) for p in hashes}
    with ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
        assert manifest['train_ids'] == ['train_q']
        assert manifest['excluded_records'] == 2
        assert manifest['train_shops'] == ['train_shop']
        assert manifest['eval_shops'] == ['dev_shop']
        assert 'data/train/answers.jsonl' not in bundle.namelist()
        assert 'data/train/questions.jsonl' not in bundle.namelist()
        for name, expected in manifest['files_sha256'].items():
            import hashlib
            assert hashlib.sha256(bundle.read(name)).hexdigest() == expected
        train = [json.loads(line) for line in bundle.read('training/train.jsonl').decode().splitlines()]
        assert [r['id'] for r in train] == ['train_q']
        assert train[0]['messages'][-1]['content'] == '```python\nprint(1)\n```'
    with pytest.raises(FileExistsError):
        package(dataset, selection, split, tmp_path / 'output')
    with pytest.raises(ValueError, match='read-only'):
        package(dataset, selection, split, split / 'output')


def test_colab_notebook_is_clean_and_keeps_training_separate_from_dev():
    notebook = nbformat.read(ROOT / 'notebooks/Train_DeepSeek_R1_14B_code_only_Colab.ipynb', as_version=4)
    nbformat.validate(notebook)
    for cell in notebook.cells:
        if cell.cell_type == 'code':
            compile(cell.source, cell.id, 'exec')
            assert cell.outputs == [] and cell.execution_count is None
    code = '\n'.join(c.source for c in notebook.cells if c.cell_type == 'code')
    assert "'--completion_format', 'r1-code-only'" in code
    assert "'--data', str(INPUT / 'training/train.jsonl')" in code
    assert "'--prompt-variant', 'baseline'" in code
    assert code.index('BASE_REPORT = evaluate') < code.index("'--smoke'")
    assert code.index("'--smoke'") < code.index("ADAPTER = RUN_ROOT")
    assert 'torch.cuda.device_count() != 1' in code
    assert 'files.upload(' not in code
    assert "repo_type='dataset'" in code
    assert 'revision=BUNDLE_REVISION, token=HF_TOKEN' in code
    assert "USE_TF='0', USE_TORCH='1'" in code
    assert "TRAIN_ARGS.append('--load_in_4bit')" in code


@pytest.mark.parametrize('failure', [None, 'zip-hash', 'file-hash', 'traversal'])
def test_hf_download_cell_pins_source_and_checks_hashes_before_execution(tmp_path, monkeypatch, capsys, failure):
    notebook = nbformat.read(ROOT / 'notebooks/Train_DeepSeek_R1_14B_code_only_Colab.ipynb', as_version=4)
    source = notebook.cells[6].source
    contents = b'train fixture'
    manifest = dict(format='datamate-r1-code-only-v1', files_sha256={
        'training/train.jsonl': hashlib.sha256(contents).hexdigest()},
        train_ids=['train'], eval_ids=['dev'], train_shops=['train_shop'], eval_shops=['dev_shop'],
        train_records=1, eval_records=1, validation_scope='fixture')
    archive = tmp_path / 'fixture.zip'
    with ZipFile(archive, 'w') as bundle:
        bundle.writestr('manifest.json', json.dumps(manifest))
        bundle.writestr('training/train.jsonl', b'changed' if failure == 'file-hash' else contents)
        if failure == 'traversal':
            bundle.writestr('../outside.py', 'raise RuntimeError("must not execute")')
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    if failure == 'zip-hash':
        expected = '0' * 64
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        return str(archive)

    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(hf_hub_download=download))
    work = tmp_path / 'work'
    run = tmp_path / 'run'
    run.mkdir()
    import zipfile
    ns = dict(Path=Path, json=json, hashlib=hashlib, zipfile=zipfile, WORK=work, RUN_ROOT=run,
              HF_TOKEN='fixture-secret', BUNDLE_REPO='owner/private-handoff', BUNDLE_REVISION='a' * 40,
              BUNDLE_FILENAME='bundle.zip', BUNDLE_SHA256=expected)
    if failure:
        with pytest.raises(ValueError):
            exec(source, ns)
        assert not (tmp_path / 'outside.py').exists()
    else:
        exec(source, ns)
        recorded = json.loads((run / 'bundle_source.json').read_text())
        assert recorded['revision'] == 'a' * 40 and recorded['sha256'] == expected
        assert 'fixture-secret' not in json.dumps(recorded)
    assert calls[0]['token'] == 'fixture-secret'
    assert calls[0]['repo_type'] == 'dataset' and calls[0]['revision'] == 'a' * 40
    assert 'fixture-secret' not in capsys.readouterr().out


@pytest.mark.parametrize('gib,choice,expected', [(39.49, None, True), (79.25, None, False),
    (79.25, True, True), (39.49, False, 'error')])
def test_colab_selects_qlora_for_a100_40gb(tmp_path, monkeypatch, gib, choice, expected):
    notebook = nbformat.read(ROOT / 'notebooks/Train_DeepSeek_R1_14B_code_only_Colab.ipynb', as_version=4)
    calls = []
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: True, device_count=lambda: 1,
        get_device_properties=lambda i: SimpleNamespace(name='NVIDIA A100', total_memory=gib * 2**30))))
    ns = dict(sys=sys, LOAD_IN_4BIT=choice, subprocess=SimpleNamespace(run=lambda command, **kw: calls.append(command)))
    if expected == 'error':
        with pytest.raises(RuntimeError, match='40GB'):
            exec(notebook.cells[4].source, ns)
    else:
        exec(notebook.cells[4].source, ns)
        assert ns['LOAD_IN_4BIT'] is expected
        assert any(any('bitsandbytes' in item for item in command) for command in calls) == expected


@pytest.mark.parametrize('bad_hash', [False, True])
def test_in_session_hotfix_preserves_inputs_and_uses_fresh_smoke(tmp_path, monkeypatch, bad_hash):
    import ast
    import os
    source = (ROOT / 'scripts/colab_r1_40gb_hotfix.py').read_text(encoding='utf-8')
    expected = next(ast.literal_eval(n.value) for n in ast.parse(source).body
                    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'expected' for t in n.targets))
    trainer = tmp_path / 'trainer.py'
    trainer.write_bytes(b'# test fixture trainer')
    if not bad_hash:
        source = source.replace(expected, hashlib.sha256(trainer.read_bytes()).hexdigest())
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(hf_hub_download=lambda **kw: str(trainer)))
    installs = []
    import subprocess
    monkeypatch.setattr(subprocess, 'run', lambda command, **kw: installs.append(command))
    for name in ('PYTHONPATH', 'USE_TF', 'USE_TORCH', 'PYTORCH_CUDA_ALLOC_CONF'):
        monkeypatch.setenv(name, 'original')
    root = tmp_path / 'run'
    (root / 'smoke').mkdir(parents=True)
    sentinel = root / 'smoke/old.log'
    sentinel.write_text('failed original run')
    bundle = tmp_path / 'verified_bundle'
    bundle.mkdir()
    args = [sys.executable, '-B', '-u', 'old_train.py', '--data', 'original_train.jsonl']
    calls = []

    def run_logged(command, log_path):
        calls.append(command)
        assert command[3] == str(trainer)
        assert '--load_in_4bit' in command and '--smoke' in command
        output = Path(command[command.index('--output_dir') + 1])
        assert output != root / 'smoke'
        (output / 'checkpoints').mkdir(parents=True)
        (output / 'checkpoints/train_results.json').write_text('{"train_loss": 1}')

    ns = dict(HF_TOKEN='fixture-secret', RUN_ROOT=root, INPUT=bundle, TRAIN_ARGS=args, run_logged=run_logged)
    if bad_hash:
        with pytest.raises(ValueError, match='hash mismatch'):
            exec(source, ns)
        assert not installs and not calls
    else:
        exec(source, ns)
        assert len(calls) == 1 and installs
        assert os.environ['USE_TF'] == '0' and os.environ['USE_TORCH'] == '1'
        assert os.environ['PYTHONPATH'].startswith(str(bundle))
        assert args[3] == str(trainer)
        assert (root / 'training_hotfix.json').is_file()
    assert sentinel.read_text() == 'failed original run'
