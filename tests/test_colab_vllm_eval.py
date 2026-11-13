import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import nbformat
import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'notebooks/Train_DeepSeek_R1_14B_code_only_Colab.ipynb'


def code_cells():
    return {c.id: c.source for c in nbformat.read(NOTEBOOK, as_version=4).cells if c.cell_type == 'code'}


def test_vllm_installs_only_into_isolated_environment(tmp_path):
    calls = []
    ns = dict(Path=Path, WORK=tmp_path, RUN_ROOT=tmp_path, sys=sys, os=os,
              subprocess=SimpleNamespace(run=lambda command, **kwargs: calls.append((command, kwargs))))
    exec(code_cells()['colab-vllm-environment'], ns)
    assert calls[0][0][:4] == [sys.executable, '-m', 'venv', '--without-pip']
    assert '--system-site-packages' not in calls[0][0]
    install = calls[1][0]
    assert install[:5] == [sys.executable, '-m', 'pip', '--python', str(ns['EVAL_PYTHON'])]
    assert 'vllm==0.33.0' in install and 'pandas==2.3.3' in install
    assert not any(arg.startswith(('transformers==', 'torch==', 'peft==')) for arg in install)
    assert ns['EVAL_ENV'].name == 'vllm_0_33_0_pandas_2_3_3'
    assert calls[2][0][0] == str(ns['EVAL_PYTHON'])
    assert calls[2][1]['env']['USE_TF'] == '0'
    compile(calls[2][0][2], '<venv-check>', 'exec')


@pytest.mark.parametrize('max_seqs,eager', [(None, False), (4, True)])
def test_base_and_adapter_use_same_vllm_settings_in_separate_processes(tmp_path, max_seqs, eager):
    calls = []

    def run_logged(command, log_path):
        calls.append(command)
        out = Path(command[command.index('--output-dir') + 1])
        out.mkdir()
        (out / 'evaluation_report.json').write_text(json.dumps(dict(total_questions=30, penalized_accuracy=0)))

    ns = dict(Path=Path, json=json, RUN_ROOT=tmp_path, INPUT=tmp_path / 'input', MODEL_DIR=tmp_path / 'model',
              EVAL_PYTHON=tmp_path / 'eval/bin/python', EVAL_MAX_MODEL_LEN=16384, EVAL_MAX_TOKENS=4096,
              EVAL_MAX_NUM_SEQS=max_seqs, EVAL_ENFORCE_EAGER=eager, EVAL_GPU_MEMORY_UTILIZATION=0.90,
              manifest=dict(eval_records=30), run_logged=run_logged)
    exec(code_cells()['colab-vllm-evaluate'], ns)
    adapter = tmp_path / 'adapter'
    ns['evaluate']('adapter_dev_vllm', adapter)
    base, tuned = calls
    assert base[0] == tuned[0] == str(ns['EVAL_PYTHON'])
    for command in calls:
        assert command[command.index('--backend') + 1] == 'vllm'
        assert command[command.index('--dtype') + 1] == 'bfloat16'
        assert command[command.index('--prompt-variant') + 1] == 'baseline'
        assert command[command.index('--max-model-len') + 1] == '16384'
        assert command[command.index('--max-tokens') + 1] == '4096'
        assert command[command.index('--tensor-parallel-size') + 1] == '1'
        assert '--load-in-4bit' not in command
        assert ('--max-num-seqs' in command) == (max_seqs is not None)
        assert ('--enforce-eager' in command) == eager
    assert tuned[-2:] == ['--adapter-path', str(adapter)] and '--adapter-path' not in base
    base_shared = base[:base.index('--output-dir')] + base[base.index('--output-dir') + 2:]
    tuned_shared = tuned[:tuned.index('--output-dir')] + tuned[tuned.index('--output-dir') + 2:-2]
    assert base_shared == tuned_shared
    with pytest.raises(FileExistsError):
        ns['evaluate']('base_dev_vllm')
    assert len(calls) == 2


@pytest.mark.parametrize('backend', ['train', 'vllm'])
def test_logged_evaluation_removes_allocator_settings_and_hf_tokens_only_for_vllm(tmp_path, monkeypatch, backend):
    source = next(s for s in code_cells().values() if 'def run_logged(' in s)
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'run_logged')
    calls = []

    class Process:
        stdout = iter(['fixture output\n'])
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def wait(self): return 0

    def popen(command, **kwargs):
        calls.append(kwargs)
        return Process()

    monkeypatch.setenv('HF_TOKEN', 'fixture-secret')
    monkeypatch.setenv('PYTORCH_ALLOC_CONF', 'expandable_segments:True')
    ns = dict(Path=Path, INPUT=tmp_path, os=os, subprocess=SimpleNamespace(Popen=popen, PIPE=-1, STDOUT=-2))
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<run-logged>', 'exec'), ns)
    command = ['python', 'train.py'] if backend == 'train' else ['venv/bin/python', 'eval.py', '--backend', 'vllm']
    ns['run_logged'](command, tmp_path / 'run.log')
    environment = calls[0]['env']
    assert 'HF_TOKEN' not in environment and environment['HF_HUB_OFFLINE'] == '1'
    if backend == 'vllm':
        assert 'PYTORCH_CUDA_ALLOC_CONF' not in environment and 'PYTORCH_ALLOC_CONF' not in environment
        assert environment['VLLM_WORKER_MULTIPROC_METHOD'] == 'spawn'
    else:
        assert environment['PYTORCH_CUDA_ALLOC_CONF'] == 'expandable_segments:True'


def test_vllm_eval_does_not_reuse_transformers_report_or_change_handoff_order():
    n = nbformat.read(NOTEBOOK, as_version=4)
    text = '\n'.join(c.source for c in n.cells if c.cell_type == 'code')
    assert "BASE_REPORT = evaluate('base_dev_vllm')" in text
    assert "ADAPTER_REPORT = evaluate('adapter_dev_vllm', ADAPTER)" in text
    assert "'--backend', 'transformers'" not in text
    assert text.index("BASE_REPORT = evaluate") < text.index("'--smoke'")
    assert text.index("ADAPTER_REPORT = evaluate") < text.index('runtime.unassign()')
