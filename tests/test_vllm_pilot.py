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
    nb = json.loads((root / 'notebooks/Train_Qwen_kaggle.ipynb').read_text(encoding='utf-8'))
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
    assert "EVAL_DATA = eval_bundle / 'data/train'" in source[evaluate]
    assert source[evaluate].index('if shop_overlap:') < source[evaluate].index('subprocess.Popen')
    assert '--gold-file' not in source[train] and 'pilot_gold' not in source[train]
    assert "'--system-site-packages', '--without-pip'" in source[install]


@pytest.mark.parametrize('vram_gib,capability,tp,override,batch_size,quantized', [
    (15, (7, 5), 2, None, 1, False),
    (15, (7, 5), 1, None, 1, True),
    (24, (8, 9), 1, None, 4, False),
    (80, (9, 0), 1, None, 16, False),
    (80, (9, 0), 1, 3, 3, False),
])
def test_pilot_runs_vllm_config_and_writes_score_report(
    tmp_path, monkeypatch, vram_gib, capability, tp, override, batch_size, quantized
):
    import scripts.evaluate_pilot_30 as pilot
    base, adapter = make_inputs(tmp_path)
    questions = tmp_path / 'questions.jsonl'
    gold = tmp_path / 'gold.jsonl'
    output = tmp_path / 'evaluation'
    question_rows = [dict(id=f'q{i}', business_id='biz1', question='Count rows', as_of_date='2026-05-29')
                     for i in range(18)]
    questions.write_text('\n'.join(map(json.dumps, question_rows)))
    gold.write_text('\n'.join(json.dumps(dict(id=f'q{i}', type='unanswerable' if i == 1 else 'number',
                                               answer=None if i == 1 else 1)) for i in range(len(question_rows))))
    count = len(question_rows)
    variant = 'core'
    options = []
    if override is not None:
        excluded = tmp_path / 'excluded.jsonl'
        excluded.write_text(json.dumps(question_rows[-1]))
        count -= 1
        variant = 'baseline'
        options = ['--max-num-seqs', str(override), '--prompt-variant', variant,
                   '--exclude-questions-file', str(excluded)]
    configs = []
    sizes = []
    class Agent:
        def __init__(self, config, data_dir):
            configs.append(config)
        @staticmethod
        def answer(question):
            if question.id == 'q0':
                prediction = pilot.SubmissionItem(id=question.id, type='number', answer=1)
            elif question.id in {'q1', 'q2'}:
                prediction = pilot.SubmissionItem(id=question.id, type='unanswerable', answer=None)
            else:
                prediction = pilot.SubmissionItem.abstain(question.id)
            trace = dict(id=question.id, preflight={'cache_hit': question.id != 'q0', 'seconds': 0.1},
                         attempts=[{'prompt_messages': [{'role': 'user', 'content': 'count'}]}])
            return prediction, trace
        def answer_question_with_trace(self, question):
            sizes.append(1)
            return self.answer(question)
        def answer_questions_with_trace(self, questions):
            sizes.append(len(questions))
            return [self.answer(question) for question in questions]
    monkeypatch.setattr(pilot, 'DataMateAgent', Agent)
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: True, device_count=lambda: tp, get_device_name=lambda i: 'Mock GPU',
        get_device_capability=lambda i: capability,
        get_device_properties=lambda i: SimpleNamespace(total_memory=vram_gib * 1024**3))))
    monkeypatch.setenv('DATAMATE_ALLOW_ONLINE', '0')
    monkeypatch.delenv('PYTORCH_CUDA_ALLOC_CONF', raising=False)
    monkeypatch.setattr(sys, 'argv', ['pilot', '--backend', 'vllm', '--tensor-parallel-size', str(tp),
        '--base-model', str(base), '--adapter-path', str(adapter), '--questions-file', str(questions),
        '--gold-file', str(gold), '--data-dir', str(tmp_path), '--output-dir', str(output),
        *options])
    pilot.main()
    report = json.loads((output / 'evaluation_report.json').read_text())
    assert report['penalized_accuracy'] == pytest.approx(1 / count)
    assert report['correct'] == 2 and report['abstain'] == count - 3
    assert report['backend'] == 'vllm' and report['seconds_per_question'] >= 0
    assert report['baseline_pa'] is None and report['delta_pa'] is None
    assert configs[0]['model']['load_in_4bit'] is quantized
    assert configs[0]['model']['max_num_seqs'] == report['max_num_seqs'] == batch_size
    assert configs[0]['agent']['eval_core_rules'] == (variant == 'core')
    assert report['prompt_variant'] == variant and report['total_questions'] == count
    assert report['unanswerable'] == {'correct': 1, 'wrong': 1}
    assert report['model_turns'] == count and report['prompt_tokens'] is None
    assert report['preflight']['cold']['count'] == 1 and report['preflight']['cache_hit']['count'] == count - 1
    assert sizes == [min(batch_size, count - i) for i in range(0, count, batch_size)]
    assert configs[0]['model']['local_model_dir'] == str(base.resolve())
    assert pilot.os.environ['DATAMATE_ALLOW_ONLINE'] == '0'
    assert 'PYTORCH_CUDA_ALLOC_CONF' not in pilot.os.environ
