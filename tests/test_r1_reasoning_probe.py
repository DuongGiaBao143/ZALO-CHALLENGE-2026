import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import nbformat
import pytest

from scripts import r1_reasoning_probe as probe

ROOT = Path(__file__).resolve().parents[1]


def test_notebook_compiles_and_embedded_probe_matches_source():
    book = nbformat.read(ROOT / 'notebooks/Probe_DeepSeek_R1_14B_Reasoning_Colab.ipynb', as_version=4)
    nbformat.validate(book)
    cells = {cell.id: cell.source for cell in book.cells}
    for cell in book.cells:
        if cell.cell_type == 'code':
            compile(cell.source, cell.id, 'exec')
            assert cell.outputs == [] and cell.execution_count is None
    bootstrap = cells['bootstrap'].split('sys.path.insert', 1)[0]
    # Only decode the embedded literal, without writing to /content.
    import ast
    tree = ast.parse(bootstrap)
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'payload' for t in node.targets))
    data = base64.b64decode(ast.literal_eval(assignment.value.args[0]))
    with ZipFile(io.BytesIO(data)) as bundle:
        assert bundle.read('r1_reasoning_probe.py') == (ROOT / 'scripts/r1_reasoning_probe.py').read_bytes()
        assert bundle.read('src/agent/__init__.py') == b''
        for name in bundle.namelist():
            if name.startswith('src/') and name != 'src/agent/__init__.py':
                assert bundle.read(name) == (ROOT / name).read_bytes()
    assert 'trust_remote_code=False' in cells['load-model']
    assert 'preflight(**PATHS)' in cells['configure']
    assert list(cells).index('configure') < list(cells).index('load-model')


@pytest.mark.parametrize('raw,prefix,thinking,final,complete', [
    ('inspect\n</think>\n```python\nprint(1)\n```', True, '\ninspect\n', '\n```python\nprint(1)\n```', True),
    ('<think>inspect</think>code', True, 'inspect', 'code', True),
    ('reason ```python\nprint(99)\n```', True, '\nreason ```python\nprint(99)\n```', '', False),
    ('plain final', False, '', 'plain final', True),
])
def test_split_preserves_model_text_and_never_executes_unfinished_thought(raw, prefix, thinking, final, complete):
    assert probe.split_thinking(raw, prefix) == dict(thinking=thinking, final_text=final, thinking_complete=complete)


@pytest.mark.parametrize('member', ['../escape.csv', '/escape.csv',
                                    'data/answers.jsonl', 'data/gold.jsonl', 'data/code.py'])
def test_data_zip_rejects_unsafe_members_before_extracting(tmp_path, member):
    archive = tmp_path / 'upload.zip'
    with ZipFile(archive, 'w') as bundle:
        bundle.writestr('data/valid.csv', 'value\n1\n')
        info = ZipInfo('placeholder')
        info.filename = member
        bundle.writestr(info, 'no')
    with pytest.raises(ValueError):
        probe.extract_data(archive, tmp_path / 'out')
    assert not (tmp_path / 'out/data/valid.csv').exists()


def test_zip_accepts_context_without_overwrite(tmp_path):
    archive = tmp_path / 'upload.zip'
    with ZipFile(archive, 'w') as bundle:
        bundle.writestr('data/train/data/shop/README.md', 'context')
        bundle.writestr('data/train/questions.jsonl', '{}')
    probe.extract_data(archive, tmp_path / 'out')
    with pytest.raises(ValueError, match='overwrite'):
        probe.extract_data(archive, tmp_path / 'out')
    assert (tmp_path / 'out/data/train/data/shop/README.md').read_text() == 'context'


@pytest.fixture
def paths(tmp_path):
    business = tmp_path / 'shop'
    business.mkdir()
    (business / 'sales.csv').write_text('value\n1\n2\n', encoding='utf-8')
    rulebook = tmp_path / 'rulebook.md'
    rulebook.write_text('Sum value.', encoding='utf-8')
    calendar = tmp_path / 'calendar.csv'
    calendar.write_text('date\n2026-11-07\n', encoding='utf-8')
    return dict(runtime=ROOT, business=business, rulebook=rulebook, calendar=calendar,
                as_of_date='2026-11-07')


@pytest.mark.parametrize('incomplete', [False, 'unclosed_think', 'token_limit'])
def test_probe_records_raw_output_and_executes_only_final_code(tmp_path, monkeypatch, paths, incomplete):
    replies = [
        'Ignore this thought code: ```python\nraise Exception(99)\n```\n</think>\n```python\nprint("observe")\n```',
        'Use observed sum</think>\n```python\nprint("final")\n```',
    ]
    if incomplete == 'unclosed_think':
        replies = ['still thinking ```python\nraise Exception(99)\n```']
    calls, messages = [], []

    def generate(history):
        messages.append(list(history))
        return dict(raw_output=replies[len(messages) - 1], prefix_has_think=True,
                    finish_reason='length' if incomplete == 'token_limit' else 'eos', generated_token_ids=[1, 2])

    def execute(code, **kwargs):
        calls.append(code)
        if len(calls) == 1:
            return dict(success=True, kind='observation', parsed_output=dict(data={'sum': 3}))
        return dict(success=True, kind='final', parsed_output=dict(type='number', answer=3.14159, evidence='sum'))

    monkeypatch.setattr(probe, 'execute_code', execute)
    question = dict(id='fixture', business_id='shop', question='Sum?', as_of_date='2026-11-07')
    folder = probe.run_probe(question, paths=paths, generate=generate,
                             output_root=tmp_path / 'logs', settings={'use_4bit': True})
    trace = json.loads((folder / 'trace.json').read_text(encoding='utf-8'))
    assert (folder / 'turn_1_raw_output.txt').read_text(encoding='utf-8') == replies[0]
    assert trace['turns'][0]['generated_token_ids'] == [1, 2]
    if incomplete:
        assert not calls and trace['answer']['type'] == 'abstain'
    else:
        assert calls == ['print("observe")', 'print("final")']
        assert trace['answer'] == dict(id='fixture', type='number', answer=3.14)
        assert '"sum": 3' in messages[1][-1]['content']


def test_sandbox_command_has_no_host_root_or_secrets_bind(monkeypatch, tmp_path, paths):
    monkeypatch.setattr(probe.shutil, 'which', lambda name: '/usr/bin/bwrap')
    command = probe.sandbox_command(paths['runtime'], paths['business'], paths['rulebook'], paths['calendar'], tmp_path)
    assert '--unshare-all' in command and '--clearenv' in command
    assert '--new-session' in command and '--cap-drop' in command
    assert '--proc' not in command
    index = command.index('/proc')
    assert command[index - 1] == '--dir'
    assert str(paths['business'].resolve()) in command
    assert '/' not in command and '/root' not in command and '/content' not in command
    (paths['business'] / 'answers.jsonl').write_text('{}')
    with pytest.raises(ValueError, match='data only'):
        probe.sandbox_command(paths['runtime'], paths['business'], paths['rulebook'], paths['calendar'], tmp_path)


def test_no_unsandboxed_fallback_on_namespace_failure(monkeypatch, paths, tmp_path):
    monkeypatch.setattr(probe.tempfile, 'tempdir', str(tmp_path))
    monkeypatch.setattr(probe, 'sandbox_command', lambda *args: ['bwrap'])
    monkeypatch.setattr(probe.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stderr='Operation not permitted'))
    with pytest.raises(RuntimeError, match='no unsandboxed fallback'):
        probe.execute_code('print(1)', **paths)


def test_execution_avoids_colab_proc_mount_failure(monkeypatch, paths, tmp_path):
    monkeypatch.setattr(probe.tempfile, 'tempdir', str(tmp_path))
    monkeypatch.setattr(probe.shutil, 'which', lambda name: '/usr/bin/bwrap')
    result = dict(success=True, kind='final', parsed_output=dict(type='boolean', answer=True))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if '--proc' in command:
            return SimpleNamespace(returncode=1, stderr="bwrap: Can't mount proc on /newroot/proc: Permission denied")
        return SimpleNamespace(returncode=0, stdout=json.dumps(result))

    monkeypatch.setattr(probe.subprocess, 'run', run)
    assert probe.execute_code('print(1)', **paths) == result
    assert len(calls) == 1
    assert '--unshare-all' in calls[0] and '--clearenv' in calls[0]


@pytest.mark.parametrize('variant', ['baseline', 'core'])
@pytest.mark.parametrize('feedback', ['observation', 'error'])
def test_every_prompt_matches_real_pipeline_including_followup_and_last_turn(
        variant, feedback, tmp_path, monkeypatch, paths):
    from src.agent.prompts import SYSTEM_PROMPT
    from src.agent.sandbox import SandboxResult
    from src.agent.solver import DataMateAgent
    from src.schemas import QuestionItem

    question = dict(id='fixture', business_id='shop', question='tháng này tổng giá trị nhập hàng?',
                    as_of_date=paths['as_of_date'])
    replies = ['<think>inspect</think>\n```python\nprint("inspect")\n```',
               '<think>sum</think>\n```python\nprint("sum")\n```']
    if feedback == 'observation':
        first = dict(success=True, kind='observation', parsed_output=dict(
            kind='observation', data={'sum': 3}, message='fixture'))
    else:
        first = dict(success=False, kind='error', error_kind='runtime_error',
                     error_message='ZeroDivisionError: fixture')
    last = dict(success=True, kind='final', parsed_output=dict(
        kind='final', type='number', answer=3, evidence='sales.csv value sum'))
    reference_messages, probe_messages = [], []

    def reference_generate(messages):
        reference_messages.append([dict(message) for message in messages])
        return replies[len(reference_messages) - 1]

    reference_results = iter([first, last])
    monkeypatch.setattr(probe.solver, 'run_python_in_sandbox',
                        lambda **kwargs: SandboxResult(**next(reference_results)))
    reference = DataMateAgent(dict(agent=dict(max_turns=2, max_code_executions=2,
        eval_core_rules=variant == 'core', abstain_on_unanswerable=True)),
        paths['rulebook'].parent, backend=SimpleNamespace(generate=reference_generate))
    reference_answer, _ = reference.answer_question_with_trace(QuestionItem.from_dict(question))

    def generate(messages):
        probe_messages.append([dict(message) for message in messages])
        return dict(raw_output=replies[len(probe_messages) - 1], finish_reason='eos')

    probe_results = iter([first, last])
    monkeypatch.setattr(probe, 'execute_code', lambda code, **kwargs: next(probe_results))
    folder = probe.run_probe(question, paths=paths, generate=generate,
        output_root=tmp_path / 'logs', settings={'prompt_variant': variant}, max_turns=2)
    assert probe_messages == reference_messages
    assert probe_messages[0][0] == dict(role='system', content=SYSTEM_PROMPT)
    assert '2026-11-01 .. 2026-11-07' in probe_messages[0][1]['content']
    assert 'Đây là lượt cuối' in probe_messages[1][-1]['content']
    assert json.loads((folder / 'prompt_messages.json').read_text(encoding='utf-8')) == reference_messages[0]
    assert json.loads((folder / 'answer.json').read_text()) == reference_answer.to_dict()
    assert (folder / 'pipeline_trace.json').is_file()
