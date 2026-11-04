"""Portable SFT context reconstruction and execution after moving the data split."""
import json
import shutil

import pytest

from scripts.build_sft_dataset import build_sft_dataset, build_sft_records
from scripts.train_sft_kaggle_2t4 import inspect_dataset
from src.agent.solver import DataMateAgent, ScriptedBackend
from src.schemas import QuestionItem


CODE = """import json
import pandas as pd
df = pd.read_csv(BUSINESS_DIR / 'sales.csv')
print(json.dumps({'kind': 'final', 'type': 'number', 'answer': int(df['amount'].sum()),
                  'evidence': 'sales.csv amount sum'}))"""


@pytest.fixture
def compact_data(tmp_path):
    split = tmp_path / 'original' / 'train'
    shop = split / 'data' / 'biz_test'
    shop.mkdir(parents=True)
    (shop / 'sales.csv').write_text('amount\n10\n20\n', encoding='utf-8')
    (shop / 'README.md').write_text('One row per sale.', encoding='utf-8')
    (split / 'rulebook.md').write_text('Sum amount.', encoding='utf-8')
    (split / 'calendar.csv').write_text('solar_date,lunar_date\n2026-09-07,2026-07-26\n', encoding='utf-8')
    question = dict(id='q_test', business_id='biz_test', question='Total amount?', as_of_date='2026-09-07')
    (split / 'questions.jsonl').write_text(json.dumps(question) + '\n', encoding='utf-8')
    compact = tmp_path / 'sft.jsonl'
    compact.write_text(json.dumps(dict(id='q_test', business_id='biz_test', code=CODE)) + '\n', encoding='utf-8')
    return compact, split, question


def test_relocated_context_matches_inference_and_executes(compact_data, tmp_path):
    compact, original, question = compact_data
    moved = tmp_path / 'kaggle' / 'input' / 'train'
    shutil.copytree(original, moved)
    original_bytes = compact.read_bytes()
    expected = build_sft_records(str(compact), str(original))
    assert expected == build_sft_records(str(compact), str(moved))
    assert str(original) not in expected[0]['messages'][1]['content']
    assert str(moved) not in expected[0]['messages'][1]['content']
    agent = DataMateAgent(
        {'agent': {'sandbox_timeout_sec': 25}, 'paths': {'work_dir': str(tmp_path / 'work')}},
        data_dir=moved, backend=ScriptedBackend([expected[0]['messages'][-1]['content']]),
    )
    answer, trace = agent.answer_question_with_trace(QuestionItem.from_dict(question))
    assert trace['initial_user_prompt'] == expected[0]['messages'][1]['content']
    assert trace['system_prompt'] == expected[0]['messages'][0]['content']
    assert answer.type == 'number' and answer.answer == 30
    assert compact.read_bytes() == original_bytes


@pytest.mark.parametrize('change, message', [
    ({'id': 'missing'}, 'not found'),
    ({'business_id': 'another_shop'}, 'business_id mismatch'),
    ({'code': ''}, 'Missing Python code'),
])
def test_invalid_compact_record_fails_instead_of_dropping_it(compact_data, change, message):
    compact, split, _ = compact_data
    row = json.loads(compact.read_text())
    row.update(change)
    compact.write_text(json.dumps(row), encoding='utf-8')
    with pytest.raises(ValueError, match=message):
        build_sft_records(str(compact), str(split))


def test_builder_and_kaggle_preflight_accept_compact_records(compact_data, tmp_path):
    compact, split, _ = compact_data
    output = tmp_path / 'prepared.jsonl'
    build_sft_dataset(str(compact), str(split), str(output))
    assert json.loads(output.read_text())['messages'][-1]['content'] == f'```python\n{CODE}\n```'

    class Tokenizer:
        def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, return_dict):
            text = ''.join(f"<{m['role']}>{m['content']}</>" for m in messages)
            return list((text + ('<assistant>' if add_generation_prompt else '')).encode())

    report = inspect_dataset(compact, Tokenizer(), 20000, expected_rows=1, data_train_dir=str(split))
    prepared = inspect_dataset(output, Tokenizer(), 20000, expected_rows=1)
    assert report == prepared
    assert not report['overlength']


def test_profile_prompt_never_contains_host_location():
    from src.profiler.business_loader import format_profile_for_prompt
    from src.schemas import BusinessProfile

    paths = [r'D:\Users\owner\project\data\biz_test', '/kaggle/input/data/biz_test', '/data/data/biz_test']
    prompts = [format_profile_for_prompt(BusinessProfile('biz_test', p, 'Shop rules'), compact=True) for p in paths]
    assert len(set(prompts)) == 1
    assert all(path not in prompts[0] for path in paths)
