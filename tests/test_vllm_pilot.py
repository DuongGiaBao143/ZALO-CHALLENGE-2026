import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from safetensors.numpy import save_file

from src.agent.solver import VLLMBackend


def make_inputs(tmp_path, wrapped=False):
    base = tmp_path / 'base'
    base.mkdir()
    (base / 'config.json').write_text('{}')
    (base / 'tokenizer.json').write_text('{}')
    (base / 'model.safetensors').write_bytes(b'base')
    adapter = tmp_path / 'adapter'
    adapter.mkdir()
    (adapter / 'adapter_config.json').write_text(json.dumps(dict(r=16)))
    key = 'base_model.model.model.layers.0.' + ('_checkpoint_wrapped_module.' if wrapped else '') + 'mlp.up_proj.lora_A.weight'
    save_file({key: np.zeros((16, 8), dtype=np.float32)}, adapter / 'adapter_model.safetensors')
    return base, adapter


def test_vllm_enables_lora_and_passes_it_on_every_chat(tmp_path, monkeypatch):
    base, adapter = make_inputs(tmp_path)
    calls = []
    class Engine:
        def __init__(self, **kwargs):
            calls.append(('init', kwargs))
        def chat(self, **kwargs):
            calls.append(('chat', kwargs))
            return [SimpleNamespace(outputs=[SimpleNamespace(text='```python\nprint(1)\n```')])]
    monkeypatch.setitem(sys.modules, 'vllm', SimpleNamespace(LLM=Engine, SamplingParams=lambda **kw: kw))
    monkeypatch.setitem(sys.modules, 'vllm.lora.request', SimpleNamespace(LoRARequest=lambda *args: args))
    backend = VLLMBackend(dict(local_model_dir=str(base), adapter_path=str(adapter), dtype='float16',
                               tensor_parallel_size=2, enforce_eager=True))
    assert calls[0][1]['enable_lora'] and calls[0][1]['max_lora_rank'] == 16
    assert calls[0][1]['tensor_parallel_size'] == 2 and calls[0][1]['enable_prefix_caching']
    messages = [dict(role='user', content='question')]
    assert 'print(1)' in backend.generate(messages)
    assert calls[-1][1]['lora_request'] == ('datamate', 1, str(adapter.resolve()))
    assert calls[-1][1]['messages'] == [messages]


def test_vllm_rejects_unrepaired_adapter_before_initializing_engine(tmp_path, monkeypatch):
    base, adapter = make_inputs(tmp_path, wrapped=True)
    monkeypatch.setitem(sys.modules, 'vllm', SimpleNamespace(LLM=lambda **kw: pytest.fail('Engine must not start')))
    with pytest.raises(ValueError, match='checkpoint wrapper'):
        VLLMBackend(dict(local_model_dir=str(base), adapter_path=str(adapter)))


def test_pilot_cli_selects_vllm_and_rejects_four_bit_combo(monkeypatch):
    from scripts.evaluate_pilot_30 import parse_args
    monkeypatch.setattr(sys, 'argv', ['pilot', '--backend', 'vllm', '--tensor-parallel-size', '2', '--enforce-eager'])
    args = parse_args()
    assert args.backend == 'vllm' and args.tensor_parallel_size == 2 and args.enforce_eager
    monkeypatch.setattr(sys, 'argv', ['pilot', '--backend', 'vllm', '--load-in-4bit'])
    with pytest.raises(SystemExit):
        parse_args()


def test_kaggle_notebook_uses_vllm_after_training_and_keeps_gold_out_of_training():
    root = Path(__file__).resolve().parents[1]
    nb = json.loads((root / 'notebooks/02_train_sft_qwen7b_kaggle_2t4_890.ipynb').read_text(encoding='utf-8'))
    source = []
    for cell in nb['cells']:
        if cell['cell_type'] == 'code':
            text = ''.join(cell['source'])
            compile(text, '<kaggle-cell>', 'exec')
            source.append(text)
    train = next(i for i, text in enumerate(source) if "str(RUN_ROOT / 'train')" in text)
    install = next(i for i, text in enumerate(source) if 'vllm==0.10.2' in text)
    evaluate = next(i for i, text in enumerate(source) if "'--backend', 'vllm'" in text)
    assert train < install < evaluate
    assert "'--tensor-parallel-size', '2'" in source[evaluate]
    assert "'evaluation/train'" in source[evaluate] and 'bundle /' in source[evaluate]
    assert '--gold-file' not in source[train] and 'pilot_gold' not in source[train]
    assert "'--system-site-packages', '--without-pip'" in source[install]


def test_pilot_runs_vllm_config_and_writes_score_report(tmp_path, monkeypatch):
    import scripts.evaluate_pilot_30 as pilot
    base, adapter = make_inputs(tmp_path)
    questions = tmp_path / 'questions.jsonl'
    gold = tmp_path / 'gold.jsonl'
    output = tmp_path / 'evaluation'
    questions.write_text('\n'.join(json.dumps(dict(id=f'q{i}', business_id='biz1',
        question='Count rows', as_of_date='2026-05-29')) for i in range(2)))
    gold.write_text('\n'.join(json.dumps(dict(id=f'q{i}', type='number', answer=1)) for i in range(2)))
    configs = []
    class Agent:
        def __init__(self, config, data_dir):
            configs.append(config)
        def answer_question_with_trace(self, question):
            prediction = (pilot.SubmissionItem(id=question.id, type='number', answer=1)
                          if question.id == 'q0' else pilot.SubmissionItem.abstain(question.id))
            return prediction, dict(id=question.id)
    monkeypatch.setattr(pilot, 'DataMateAgent', Agent)
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: True, device_count=lambda: 2, get_device_name=lambda i: 'T4',
        get_device_properties=lambda i: SimpleNamespace(total_memory=15 * 1024**3))))
    monkeypatch.setenv('DATAMATE_ALLOW_ONLINE', '0')
    monkeypatch.delenv('PYTORCH_CUDA_ALLOC_CONF', raising=False)
    monkeypatch.setattr(sys, 'argv', ['pilot', '--backend', 'vllm', '--tensor-parallel-size', '2',
        '--base-model', str(base), '--adapter-path', str(adapter), '--questions-file', str(questions),
        '--gold-file', str(gold), '--data-dir', str(tmp_path), '--output-dir', str(output)])
    pilot.main()
    report = json.loads((output / 'evaluation_report.json').read_text())
    assert report['penalized_accuracy'] == 0.5 and report['correct'] == 1 and report['abstain'] == 1
    assert report['backend'] == 'vllm' and report['seconds_per_question'] >= 0
    assert configs[0]['model']['load_in_4bit'] is False
    assert configs[0]['model']['local_model_dir'] == str(base.resolve())
    assert pilot.os.environ['DATAMATE_ALLOW_ONLINE'] == '0'
    assert 'PYTORCH_CUDA_ALLOC_CONF' not in pilot.os.environ
