"""Verify the standalone HF Colab notebook without network or a GPU."""

import ast
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest


ROOT = Path(__file__).resolve().parents[1]


def cells():
    notebook = json.loads((ROOT / 'notebooks/Danh_gia_PA_model_30_cau_Colab.ipynb').read_text(encoding='utf-8'))
    return notebook, {cell['id']: ''.join(cell['source']) for cell in notebook['cells']}


def test_notebook_is_valid_and_does_not_require_drive():
    import nbformat
    notebook, source = cells()
    nbformat.validate(nbformat.from_dict(notebook))
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            compile(''.join(cell['source']), cell['id'], 'exec')
            assert cell['outputs'] == [] and cell['execution_count'] is None
    assert 'HF_ADAPTER_FOLDER = ' in source['configure']
    assert 'EVAL_COUNT = 30' in source['configure']
    assert "HF_ADAPTER_FOLDER = ''" in source['configure']
    assert "PROMPT_FORMAT = 'user-only'" in source['configure']
    assert 'TEMPERATURE = 0.0' in source['configure']
    assert 'drive.mount' not in '\n'.join(source.values())


@pytest.mark.parametrize('installed', [True, False])
def test_vllm_pins_are_applied_even_when_packages_already_exist(monkeypatch, installed):
    import importlib.util
    _, source = cells()
    calls = []
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: object() if installed else None)
    namespace = dict(BACKEND='vllm', HF_ADAPTER_FOLDER='runs/test/final_adapter', LOAD_IN_4BIT=False,
        torch=SimpleNamespace(cuda=SimpleNamespace(get_device_capability=lambda i: (8, 0),
            get_device_properties=lambda i: SimpleNamespace(total_memory=80 * 2**30))),
        sys=sys, subprocess=SimpleNamespace(run=lambda command, **kwargs: calls.append((command, kwargs))))
    exec(source['dependencies'], namespace)
    assert len(calls) == 1 and calls[0][1]['check']
    assert 'vllm==0.33.0' in calls[0][0] and 'pandas==2.3.3' in calls[0][0]
    assert 'peft' not in calls[0][0]  # vLLM loads LoRA directly, independent of train's PEFT.
    assert "DTYPE = 'bfloat16'" in source['configure']


@pytest.mark.parametrize('selection,repo,revision', [
    ('runs/test/final_adapter', 'Crinkk/Zalo-challenge', 'main'),
    ('https://huggingface.co/Crinkk/other-repo/tree/v2/runs/test/final_adapter/',
     'Crinkk/other-repo', 'v2'),
])
def test_hf_adapter_folder_downloads_both_files_at_one_revision(tmp_path, monkeypatch, selection, repo, revision):
    _, source = cells()
    monkeypatch.setenv('HF_TOKEN', 'fake-token')
    calls = []

    def model_info(repo_id, *, revision):
        calls.append((repo_id, revision))
        return SimpleNamespace(sha='resolved-revision')

    def download(*, repo_id, revision, filename, token, local_dir):
        calls.append((repo_id, revision, filename))
        path = tmp_path / Path(filename).name
        path.write_text('{}' if path.suffix == '.json' else 'fixture')
        return str(path)

    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(
        HfApi=lambda **kwargs: SimpleNamespace(model_info=model_info), hf_hub_download=download,
    ))
    ns = dict(Path=Path, json=json, os=os, WORK=tmp_path,
              HF_ADAPTER_REPO='Crinkk/Zalo-challenge', HF_ADAPTER_FOLDER=selection)
    exec(compile(source['hf-adapter'], '<hf-adapter-cell>', 'exec'), ns)
    assert calls == [
        (repo, revision),
        (repo, 'resolved-revision', 'runs/test/final_adapter/adapter_config.json'),
        (repo, 'resolved-revision', 'runs/test/final_adapter/adapter_model.safetensors'),
    ]
    assert ns['ADAPTER_PATH'] == tmp_path
    assert ns['ADAPTER_SOURCE'] == dict(repo_id=repo, folder='runs/test/final_adapter', revision='resolved-revision')


@pytest.mark.parametrize('exit_code', [0, 3])
def test_live_output_forwards_stdout_stderr_and_preserves_failure(tmp_path, capsys, exit_code):
    _, source = cells()
    tree = ast.parse(source['evaluate-30'])
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run_live')
    namespace = dict(os=os, subprocess=subprocess, RUNTIME_DIR=tmp_path)
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<run-live>', 'exec'), namespace)
    command = [sys.executable, '-u', '-c',
               f"import sys; print('MODEL_LOADING', flush=True); print('CHILD_ERROR', file=sys.stderr); sys.exit({exit_code})"]
    if exit_code:
        with pytest.raises(subprocess.CalledProcessError) as error:
            namespace['run_live'](command, tmp_path / 'console.log')
        assert error.value.returncode == exit_code
    else:
        namespace['run_live'](command, tmp_path / 'console.log')
    output = capsys.readouterr().out
    assert 'MODEL_LOADING' in output and 'CHILD_ERROR' in output
    console = (tmp_path / 'console.log').read_text()
    assert 'MODEL_LOADING' in console and 'CHILD_ERROR' in console


@pytest.mark.parametrize('count', [30, 50, 70, 2])
def test_eval_downloads_folder_files_directly_and_keeps_order(tmp_path, count):
    _, source = cells()
    snapshot = tmp_path / 'work/hf_runtime/fixture-head'
    runtime = snapshot / 'evaluation/runtime'
    (runtime / 'data/train/data/biz_fixture').mkdir(parents=True)
    ids = [f'question-{i}' for i in reversed(range(count))]
    questions = [dict(id=qid, business_id='biz_fixture') for qid in ids]
    gold = [dict(id=qid, type='number', answer=1) for qid in ids]
    names = {}
    for name, rows in [('questions.jsonl', questions), ('gold.jsonl', gold)]:
        path = tmp_path / name
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        names[f'evaluation/unseen_eval_{count}/{name}'] = path
    sft_path = tmp_path / 'sft_890_ids.json'
    seed = [f'train-{i}' for i in range(890)]
    sft_path.write_text(json.dumps(seed), encoding='utf-8')
    names['evaluation/runtime/sft_890_ids.json'] = sft_path

    downloaded = []
    def fake_file(*, filename, revision, **kwargs):
        assert revision == 'fixture-head'
        downloaded.append(filename)
        return str(names[filename])

    snapshots = []
    def fake_snapshot(*, allow_patterns, revision, local_dir, **kwargs):
        assert revision == 'fixture-head'
        assert local_dir == snapshot
        assert 'evaluation/runtime/data/train/data/biz_fixture/*' in allow_patterns
        assert not any('.zip' in p for p in allow_patterns)
        snapshots.append(allow_patterns)
        return str(snapshot)

    env = dict(WORK=tmp_path / 'work', Path=Path, json=json, get_hf_token=lambda: 'fixture-token',
               hf_hub_download=fake_file, EVAL_COUNT=count, HF_EVAL_REPO='Crinkk/Zalo-challenge', HF_EVAL_REVISION='fixture-head',
               HfApi=lambda **kw: SimpleNamespace(model_info=lambda *args, **kwargs: SimpleNamespace(sha='fixture-head')))
    from unittest.mock import patch
    with patch.dict(sys.modules, {'huggingface_hub': SimpleNamespace(snapshot_download=fake_snapshot)}):
        exec(source['runtime-source'], env)
        assert downloaded == list(names) and len(snapshots) == 1
        sft_path.write_text(json.dumps(seed[:-1] + [ids[0]]), encoding='utf-8')
        with pytest.raises(ValueError, match='trùng ID'):
            exec(source['runtime-source'], dict(env))
        assert len(snapshots) == 1

    definitions = source['evaluate-30'].rsplit('\nEVAL_OUTPUT =', 1)[0]
    env.update(datetime=datetime, ZoneInfo=ZoneInfo, sys=sys, ADAPTER_PATH=tmp_path / 'adapter',
               BASE_MODEL_PATH=tmp_path / 'base', ADAPTER_SOURCE={'revision': 'adapter-fixture'},
               MODEL_SOURCE={'repo_id': 'org/model', 'revision': 'model-head'},
               BACKEND='vllm', DTYPE='float16', LOAD_IN_4BIT=False, MAX_MODEL_LEN=8192,
               MAX_TOKENS=2048, MAX_NUM_SEQS=None, TENSOR_PARALLEL_SIZE=1, GPU_MEMORY_UTILIZATION=0.85,
               TEMPERATURE=0.0, ENABLE_THINKING=None, PROMPT_FORMAT='user-only')
    exec(definitions, env)
    def fake_run(command, log_path):
        flags = dict(zip(command[4::2], command[5::2]))
        assert Path(command[3]).name == 'evaluate_with_settings.py'
        assert Path(flags['--runtime-dir']) == runtime
        assert flags['--adapter-path'] == str(env['ADAPTER_PATH'])
        assert Path(flags['--questions-file']) == names[f'evaluation/unseen_eval_{count}/questions.jsonl']
        assert Path(flags['--gold-file']) == names[f'evaluation/unseen_eval_{count}/gold.jsonl']
        output = Path(flags['--output-dir'])
        assert log_path == output / 'console.log'
        (output / 'evaluation_report.json').write_text(json.dumps(dict(
            total_questions=count, penalized_accuracy=0, correct=0, wrong=0, abstain=count)))
    env['run_live'] = fake_run
    result = env['run_eval']()
    manifest = json.loads((result / 'runtime_manifest.json').read_text())
    assert manifest['question_ids'] == ids and manifest['sft_890_id_overlap'] == 0
    assert manifest['eval_source']['revision'] == 'fixture-head'
    assert manifest['model_source']['revision'] == 'model-head'


def test_empty_adapter_skips_auth_and_download(tmp_path, monkeypatch):
    _, source = cells()
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(
        HfApi=lambda **kw: pytest.fail('No adapter API needed'),
        hf_hub_download=lambda **kw: pytest.fail('No adapter download needed'),
    ))
    ns = dict(HF_ADAPTER_FOLDER='', HF_ADAPTER_REPO='org/repo')
    exec(source['hf-adapter'], ns)
    assert ns['ADAPTER_PATH'] is None and ns['ADAPTER_SOURCE'] is None
    assert ns['adapter_config'] == {}


@pytest.mark.parametrize('selection,folder', [
    ('https://huggingface.co/org/adapter', ''),
    ('https://huggingface.co/org/adapter/tree/v1', ''),
    ('https://huggingface.co/org/adapter/tree/v1/my/adapter', 'my/adapter'),
])
def test_adapter_accepts_repo_root_and_folder_links(tmp_path, monkeypatch, selection, folder):
    _, source = cells()
    def download(**kwargs):
        assert kwargs['filename'] == '/'.join(filter(None, (folder, Path(kwargs['filename']).name)))
        assert kwargs['revision'] == 'adapter-head'
        path = kwargs['local_dir'] / kwargs['filename']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}' if path.suffix == '.json' else 'weights')
        return str(path)
    monkeypatch.setenv('HF_TOKEN', 'fake-token')
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(
        HfApi=lambda **kw: SimpleNamespace(model_info=lambda *a, **kw: SimpleNamespace(sha='adapter-head')),
        hf_hub_download=download,
    ))
    ns = dict(Path=Path, json=json, os=os, WORK=tmp_path,
              HF_ADAPTER_REPO='unused/repo', HF_ADAPTER_FOLDER=selection)
    exec(source['hf-adapter'], ns)
    assert ns['ADAPTER_SOURCE']['repo_id'] == 'org/adapter'
    assert ns['ADAPTER_SOURCE']['folder'] == folder
    assert ns['ADAPTER_PATH'].is_relative_to(tmp_path / 'adapters')


def model_fixture(path, bin_weights=False):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'config.json').write_text('{}')
    (path / 'tokenizer.json').write_text('{}')
    weight = 'pytorch_model.bin' if bin_weights else 'model.safetensors'
    (path / weight).write_bytes(b'weights')


def model_namespace(tmp_path, **overrides):
    return dict(Path=Path, json=json, re=re, WORK=tmp_path,
                BASE_MODEL_ID='org/model-9B', BASE_MODEL_REVISION='v2', BASE_MODEL_SUBFOLDER='',
                ADAPTER_PATH=None, adapter_config={}, get_hf_token=lambda: 'fake-token', **overrides)


@pytest.mark.parametrize('folder,base_from_adapter', [('', False), ('runs/merged', False), ('', True)])
def test_base_model_download_is_selected_and_commit_pinned(tmp_path, monkeypatch, folder, base_from_adapter):
    _, source = cells()
    calls = []
    def model_info(repo_id, *, revision):
        calls.append((repo_id, revision))
        return SimpleNamespace(sha='model-head')
    def snapshot_download(**kwargs):
        assert kwargs['repo_id'] == 'org/model-9B' and kwargs['revision'] == 'model-head'
        assert kwargs['allow_patterns'] == ([f'{folder}/*'] if folder else None)
        path = kwargs['local_dir']
        model_fixture(path / folder, bin_weights=True)
        return str(path)
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(snapshot_download=snapshot_download))
    ns = model_namespace(tmp_path)
    ns.update(HfApi=lambda **kw: SimpleNamespace(model_info=model_info), BASE_MODEL_SUBFOLDER=folder)
    if base_from_adapter:
        ns.update(BASE_MODEL_ID='', ADAPTER_PATH=tmp_path / 'adapter',
                  adapter_config={'base_model_name_or_path': 'org/model-9B'})
    exec(source['base-weights'], ns)
    assert calls == [('org/model-9B', 'v2')]
    assert ns['BASE_MODEL_PATH'] == tmp_path / 'models/org/model-9B/model-head' / folder
    assert ns['MODEL_SOURCE'] == dict(repo_id='org/model-9B', folder=folder, revision='model-head')


@pytest.mark.parametrize('failure', ['wrong-base', 'missing-shard', 'missing-tokenizer', 'adapter-only', 'traversal'])
def test_model_validation_fails_before_launch(tmp_path, failure, monkeypatch):
    _, source = cells()
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(
        snapshot_download=lambda **kwargs: pytest.fail('Validation must not download weights')))
    base = tmp_path / 'local-base'
    model_fixture(base)
    ns = model_namespace(tmp_path)
    ns['BASE_MODEL_ID'] = str(base)
    if failure == 'wrong-base':
        ns.update(BASE_MODEL_ID='org/model-9B', ADAPTER_PATH=tmp_path / 'adapter',
                  adapter_config={'base_model_name_or_path': 'org/model-7B'})
    elif failure in ('missing-shard', 'traversal'):
        shard = 'missing.safetensors' if failure == 'missing-shard' else '../outside.safetensors'
        (tmp_path / 'outside.safetensors').write_bytes(b'outside')
        (base / 'model.safetensors.index.json').write_text(json.dumps({'weight_map': {'x': shard}}))
    elif failure == 'missing-tokenizer':
        (base / 'tokenizer.json').unlink()
    else:
        (base / 'model.safetensors').unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        exec(source['base-weights'], ns)


def test_local_model_requires_no_hub_download(tmp_path, monkeypatch):
    _, source = cells()
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(
        snapshot_download=lambda **kwargs: pytest.fail('Local model needs no HF download')))
    base = tmp_path / 'base'
    model_fixture(base)
    ns = model_namespace(tmp_path)
    ns.update(BASE_MODEL_ID=str(base), get_hf_token=lambda: pytest.fail('Local model needs no HF token'))
    exec(source['base-weights'], ns)
    assert ns['BASE_MODEL_PATH'] == base
    assert ns['MODEL_SOURCE'] == dict(local_path=str(base), revision=None)


@pytest.mark.parametrize('backend,adapter,fourbit,max_num_seqs,temperature,thinking', [
    ('vllm', False, False, None, 0.0, None), ('vllm', True, True, 8, 0.6, False),
    ('vllm', False, False, 16, 0.6, True), ('transformers', False, True, None, 0.0, False),
    ('transformers', False, False, 4, 0.6, None),
])
def test_run_config_reaches_evaluator_and_manifest(tmp_path, backend, adapter, fourbit, max_num_seqs, temperature, thinking):
    _, source = cells()
    ns = dict(Path=Path, json=json, re=re, datetime=datetime, ZoneInfo=ZoneInfo, sys=sys,
              WORK=tmp_path, RUNTIME_DIR=tmp_path / 'runtime', EVAL_COUNT=1,
              EVAL_SOURCE={'revision': 'eval-head'}, MODEL_SOURCE={'repo_id': 'org/other-9B', 'revision': 'base-head'},
              ADAPTER_SOURCE={'revision': 'adapter-head'} if adapter else None,
              ADAPTER_PATH=tmp_path / 'adapter' if adapter else None,
              BASE_MODEL_PATH=tmp_path / 'base', question_rows=[{'id': 'q1'}],
              BACKEND=backend, DTYPE='bfloat16', LOAD_IN_4BIT=fourbit,
              MAX_MODEL_LEN=12000, MAX_TOKENS=3000, MAX_NUM_SEQS=max_num_seqs,
              TENSOR_PARALLEL_SIZE=1, GPU_MEMORY_UTILIZATION=0.8,
              TEMPERATURE=temperature, ENABLE_THINKING=thinking, PROMPT_FORMAT='user-only')
    exec(source['evaluate-30'].rsplit('\nEVAL_OUTPUT =', 1)[0], ns)
    def fake_run(command, log_path):
        flags = command[4:]
        if fourbit:
            assert flags.pop() == '--load-in-4bit'
        pairs = dict(zip(flags[::2], flags[1::2]))
        assert pairs['--temperature'] == str(temperature)
        assert pairs['--prompt-format'] == 'user-only'
        assert pairs['--thinking'] == ('auto' if thinking is None else 'on' if thinking else 'off')
        assert pairs['--backend'] == backend and pairs['--dtype'] == 'bfloat16'
        assert pairs['--max-model-len'] == '12000' and pairs['--max-tokens'] == '3000'
        assert ('--tensor-parallel-size' in pairs) == (backend == 'vllm')
        assert ('--max-num-seqs' in pairs) == (backend == 'vllm' and max_num_seqs is not None)
        if backend == 'vllm' and max_num_seqs is not None:
            assert pairs['--max-num-seqs'] == str(max_num_seqs)
        assert ('--adapter-path' in pairs) == adapter
        if adapter:
            assert pairs['--adapter-path'] == str(ns['ADAPTER_PATH'])
        report = dict(total_questions=1, penalized_accuracy=1, correct=1, wrong=0, abstain=0)
        (Path(pairs['--output-dir']) / 'evaluation_report.json').write_text(json.dumps(report))
    ns.update(run_live=fake_run, QUESTIONS_PATH=tmp_path / 'questions', GOLD_PATH=tmp_path / 'gold', DATA_DIR=tmp_path / 'data')
    output = ns['run_eval']()
    manifest = json.loads((output / 'runtime_manifest.json').read_text())
    assert manifest['model_source'] == ns['MODEL_SOURCE']
    assert manifest['adapter_source'] == ns['ADAPTER_SOURCE']
    assert manifest['requested_settings']['backend'] == backend
    assert manifest['requested_settings']['load_in_4bit'] == fourbit
    assert manifest['requested_settings']['max_num_seqs'] == max_num_seqs
    assert manifest['requested_settings']['temperature'] == temperature
    assert manifest['requested_settings']['enable_thinking'] is thinking
    assert manifest['requested_settings']['seed'] == 42
    assert manifest['requested_settings']['prompt_format'] == 'user-only'
    compile((output / 'evaluate_with_settings.py').read_text(), '<generated-runner>', 'exec')
    assert 'other-9B' in output.name


@pytest.mark.parametrize('value', [0, -1, True, 1.5, '8'])
def test_config_rejects_invalid_max_num_seqs(monkeypatch, value):
    _, source = cells()
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: True, device_count=lambda: 1, get_device_name=lambda i: 'Mock GPU')))
    configure = source['configure'].replace('MAX_NUM_SEQS = None', f'MAX_NUM_SEQS = {value!r}')
    with pytest.raises(ValueError, match='MAX_NUM_SEQS'):
        exec(configure, {})


@pytest.mark.parametrize('setting,value', [
    ('TEMPERATURE', '-0.1'), ('TEMPERATURE', "float('nan')"), ('TEMPERATURE', "float('inf')"),
    ('TEMPERATURE', 'True'), ('TEMPERATURE', "'0.6'"),
    ('ENABLE_THINKING', '0'), ('ENABLE_THINKING', '1'), ('ENABLE_THINKING', "'False'"),
])
def test_config_rejects_invalid_generation_settings(monkeypatch, setting, value):
    _, source = cells()
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: True, device_count=lambda: 1, get_device_name=lambda i: 'Mock GPU')))
    default = '0.0' if setting == 'TEMPERATURE' else 'None'
    configure = source['configure'].replace(f'{setting} = {default}', f'{setting} = {value}')
    with pytest.raises(ValueError, match=setting):
        exec(configure, {})


@pytest.mark.parametrize('backend,thinking,temperature,legacy_vllm', [
    ('vllm', 'auto', 0.0, False), ('vllm', 'off', 0.6, False), ('vllm', 'on', 0.0, False),
    ('transformers', 'auto', 0.6, False), ('transformers', 'off', 0.0, False), ('transformers', 'on', 0.6, False),
    ('vllm', 'off', 0.0, True),
])
def test_notebook_runner_applies_settings_to_hf_runtime_without_modifying_it(tmp_path, backend, thinking, temperature, legacy_vllm):
    _, source = cells()
    assignment = ast.parse(source['evaluate-30']).body[0]
    runner_source = ast.literal_eval(assignment.value)
    runner = tmp_path / 'evaluate_with_settings.py'
    runner.write_text(runner_source, encoding='utf-8')
    runtime = tmp_path / 'runtime'
    (runtime / 'scripts').mkdir(parents=True)
    evaluator = runtime / 'scripts/evaluate_pilot_30.py'
    original = '''import argparse, json, sys
from pathlib import Path
from types import SimpleNamespace

state = {'chats': [], 'templates': [], 'seeds': []}
sys.modules['transformers'] = SimpleNamespace(set_seed=lambda seed: state['seeds'].append(seed))

class Tokenizer:
    def apply_chat_template(self, messages, **kwargs):
        state['templates'].append(kwargs.get('enable_thinking', 'default'))
        return 'prompt'

class Engine:
    def __init__(self):
        self.tokenizer = Tokenizer()
    def chat(self, messages, chat_template_kwargs=None):
        state['chats'].append(chat_template_kwargs)
        return ['reply']
    def get_tokenizer(self):
        return self.tokenizer

class EngineBackend:
    def __init__(self):
        self.llm = Engine()

class DataMateAgent:
    def __init__(self, config, data_dir):
        state['config'] = config
        self.backend = EngineBackend() if config['model']['backend'] == 'vllm' else SimpleNamespace(tokenizer=Tokenizer())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    agent = DataMateAgent(config={'model': {'backend': args.backend, 'temperature': 0.0, 'seed': 42, 'max_num_seqs': 8}}, data_dir=Path('.'))
    if args.backend == 'vllm':
        agent.backend.llm.chat(messages=[['single']])
        agent.backend.llm.chat(messages=[['first'], ['second']])
        tokenizer = agent.backend.llm.get_tokenizer()
    else:
        tokenizer = agent.backend.tokenizer
    tokenizer.apply_chat_template(['first'], tokenize=False)
    tokenizer.apply_chat_template(['second'], tokenize=True)
    args.output_dir.mkdir()
    (args.output_dir / 'observed.json').write_text(json.dumps(state))
'''
    if legacy_vllm:
        original = original.replace('def chat(self, messages, chat_template_kwargs=None):',
                                    'def chat(self, messages):')
    evaluator.write_text(original, encoding='utf-8')
    output = tmp_path / 'result'
    completed = subprocess.run([sys.executable, str(runner), '--runtime-dir', str(runtime),
        '--temperature', str(temperature), '--thinking', thinking,
        '--backend', backend, '--output-dir', str(output)], capture_output=True, text=True)
    if legacy_vllm:
        assert completed.returncode != 0
        assert 'upgrade vLLM' in completed.stderr
        assert not output.exists()
        assert evaluator.read_text(encoding='utf-8') == original
        return
    assert completed.returncode == 0, completed.stderr
    observed = json.loads((output / 'observed.json').read_text())
    expected = {'auto': 'default', 'on': True, 'off': False}[thinking]
    assert observed['config']['model']['temperature'] == temperature
    assert observed['config']['model']['max_num_seqs'] == 8
    assert observed['templates'] == [expected, expected]
    if backend == 'vllm':
        expected_kwargs = None if thinking == 'auto' else {'enable_thinking': expected}
        assert observed['chats'] == [expected_kwargs, expected_kwargs]
        assert observed['seeds'] == []
    else:
        assert observed['seeds'] == [42]
    assert evaluator.read_text(encoding='utf-8') == original
    assert f'thinking={thinking}' in completed.stdout


@pytest.mark.parametrize('prompt_format', ['user-only', 'system-user'])
def test_prompt_format_preserves_repair_turns_errors_and_actual_trace(tmp_path, prompt_format):
    _, source = cells()
    runner = tmp_path / 'runner.py'
    runner.write_text(ast.literal_eval(ast.parse(source['evaluate-30']).body[0].value), encoding='utf-8')
    runtime = tmp_path / 'runtime'
    (runtime / 'scripts').mkdir(parents=True)
    evaluator = runtime / 'scripts/evaluate_pilot_30.py'
    original = '''import argparse, json
from pathlib import Path
from types import SimpleNamespace

class DataMateAgent:
    def __init__(self, config):
        self.backend = SimpleNamespace()
    def _answer_question_steps(self, item):
        messages = [{'role': 'system', 'content': 'instructions'}, {'role': 'user', 'content': 'question'}]
        trace = dict(system_prompt='instructions', initial_user_prompt='question', attempts=[])
        for turn in range(3):
            trace['messages'] = [dict(m) for m in messages]
            snapshot = [dict(m) for m in messages]
            try:
                reply = yield snapshot
            except RuntimeError as exc:
                reply = str(exc)
            trace['attempts'].append(dict(prompt_messages=snapshot, llm_reply=reply))
            messages.extend([{'role': 'assistant', 'content': reply}, {'role': 'user', 'content': 'fix error'}])
        return {'id': item}, trace

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    agent = DataMateAgent(config={'model': {'backend': 'vllm'}})
    steps = agent._answer_question_steps('q')
    sent = [next(steps), steps.send('bad code'), steps.throw(RuntimeError('backend failure'))]
    try:
        steps.send('fixed code')
    except StopIteration as done:
        answer, trace = done.value
    args.output_dir.mkdir()
    (args.output_dir / 'observed.json').write_text(json.dumps(dict(sent=sent, trace=trace, answer=answer)))
'''
    evaluator.write_text(original, encoding='utf-8')
    output = tmp_path / 'result'
    completed = subprocess.run([sys.executable, str(runner), '--runtime-dir', str(runtime),
        '--prompt-format', prompt_format, '--output-dir', str(output)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    observed = json.loads((output / 'observed.json').read_text())
    trace = observed['trace']
    assert observed['answer'] == {'id': 'q'}
    assert [a['llm_reply'] for a in trace['attempts']] == ['bad code', 'backend failure', 'fixed code']
    assert [a['prompt_messages'] for a in trace['attempts']] == observed['sent']
    for messages in [*observed['sent'], trace['messages']]:
        if prompt_format == 'user-only':
            assert all(m['role'] != 'system' for m in messages)
            assert messages[0] == dict(role='user', content='instructions\n\nquestion')
            assert sum(m['content'].count('instructions') for m in messages) == 1
        else:
            assert messages[0] == dict(role='system', content='instructions')
            assert messages[1] == dict(role='user', content='question')
    assert len(observed['sent'][2]) == (5 if prompt_format == 'user-only' else 6)
    assert trace['initial_user_prompt'] == ('instructions\n\nquestion' if prompt_format == 'user-only' else 'question')
    assert evaluator.read_text(encoding='utf-8') == original
