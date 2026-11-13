"""Short instructions must preserve business evidence and question anchors."""

from pathlib import Path

from src.agent.prompts import (
    CORE_CHEATSHEET,
    SYSTEM_PROMPT,
    build_error_correction_prompt,
    build_observation_prompt,
    build_user_prompt,
)
from src.time_resolver.calendar_utils import load_shared_context, resolve_relative_dates


def test_evaluator_core_prompt_orders_schema_rules_readme_and_question_anchor():
    question = "Khách nào chi nhiều tiền nhất tuần này?"
    prompt = build_user_prompt(
        question, "2026-08-19", resolve_relative_dates("2026-08-19"),
        "SCHEMA_FIXTURE", rulebook_text="RULEBOOK_ROUTING_FIXTURE",
        core_rules=True, readme_text="README_FIXTURE",
    )
    assert prompt.startswith(f"Câu hỏi: {question}\nas_of_date: 2026-08-19")
    assert prompt.count(CORE_CHEATSHEET) == 1
    assert prompt.index("2026-08-17 .. 2026-08-19") < prompt.index("SCHEMA_FIXTURE")
    assert prompt.index("SCHEMA_FIXTURE") < prompt.index(CORE_CHEATSHEET) < prompt.index("README_FIXTURE")
    assert question in prompt.split("Nhắc lại nhiệm vụ:")[1]
    assert "RULEBOOK_ROUTING_FIXTURE" not in prompt and "RULEBOOK_PATH" in prompt


def test_short_prompt_keeps_full_business_evidence_and_question():
    rules = 'RULEBOOK_START\n' + 'Only valid orders count.\n' * 100 + 'RULEBOOK_END'
    schema = 'README_START\nSpecial unit: 1 box = 24 bottles.\nREADME_END\nSheet A: order_id, amount'
    prompt = build_user_prompt(
        'How much was sold yesterday?', '2026-09-07', {'yesterday': '2026-09-06'},
        schema, rulebook_text=rules, calendar_path='/data/calendar.csv',
    )
    assert rules not in prompt and schema in prompt
    assert prompt.count(schema) == 1
    assert 'RULEBOOK_PATH' in prompt
    assert '2026-09-06' in prompt and '2026-09-07' in prompt
    assert prompt.index('How much was sold yesterday?') < prompt.index('README_END')
    assert '/data/calendar.csv' not in prompt
    assert len(SYSTEM_PROMPT) < 2000


def test_bestseller_prompt_includes_product_exceptions_without_cost_rules():
    root = Path(__file__).resolve().parents[1]
    for split in ('train', 'public_test'):
        rulebook = (root / 'data' / split / 'rulebook.md').read_text(encoding='utf-8')
        prompt = build_user_prompt(
            'Top 3 mat hang ban chay tuan nay?', '2026-08-19',
            resolve_relative_dates('2026-08-19'), 'Schema', rulebook,
        )
        assert '2026-08-17 .. 2026-08-19' in prompt
        assert 'Phí phục vụ' in prompt and 'số lượng quy về đơn vị cơ bản' in prompt
        assert 'Đơn thuộc kỳ nào' in prompt
        assert 'Hàng lời nhất' not in prompt and 'Lãi gộp' not in prompt
        assert 'submission.jsonl' not in prompt


def test_month_comparison_uses_same_length_previous_period():
    dates = resolve_relative_dates('2024-03-31')
    comparison = build_user_prompt('Tháng này so với tháng rồi?', '2024-03-31', dates, 'Schema')
    previous = build_user_prompt('Tổng tháng trước?', '2024-03-31', dates, 'Schema')
    assert 'so với tháng trước (cùng số ngày' in comparison
    assert 'tháng rồi / tháng trước (theo Rulebook' not in comparison
    assert '2024-02-01 .. 2024-02-29' in previous


def test_followup_prompts_preserve_observations_errors_and_task():
    observation = build_observation_prompt({'columns': ['order_id']}, 'one row per order', 'Count orders', '2026-09-07')
    correction = build_error_correction_prompt("KeyError: 'amount'", 'runtime_error', 'Count orders', '2026-09-07')
    for prompt in [observation, correction]:
        assert 'Count orders' in prompt and '2026-09-07' in prompt
    assert 'order_id' in observation and 'one row per order' in observation
    assert "KeyError: 'amount'" in correction
    helper_error = build_error_correction_prompt("ModuleNotFoundError: No module named 'parse_vn_number'")
    assert 'gọi trực tiếp' in helper_error


def test_full_rulebook_remains_readable_from_runtime_path(tmp_path):
    rules = '# Rules\nGlobal precedence.\n## 1. Sales\nSALES_RULE\n## 2. Debt\nDEBT_RULE\n'
    path = tmp_path / 'rulebook.md'
    path.write_text(rules, encoding='utf-8')
    context = load_shared_context(tmp_path)
    assert context['rulebook_text'] == rules
    assert context['rulebook_path'] == str(path.resolve())
    assert path.read_text(encoding='utf-8') == rules


def test_agent_reads_full_rulebook_via_observation_before_computing(tmp_path):
    from unittest.mock import patch

    from src.agent.solver import DataMateAgent, ScriptedBackend
    from src.schemas import QuestionItem

    split = tmp_path / 'split'
    shop = split / 'data' / 'biz_test'
    shop.mkdir(parents=True)
    (shop / 'sales.csv').write_text('order_id,amount\na,10\nb,20\n', encoding='utf-8')
    rules = '# Rules\nGlobal precedence.\n## 1. Sales\nSUM_AMOUNT_RULE: sum amount.\n'
    (split / 'rulebook.md').write_text(rules, encoding='utf-8')
    observe = '''```python
from pathlib import Path
import json
text = Path(RULEBOOK_PATH).read_text(encoding='utf-8')
print(json.dumps({'kind':'observation','data':text,'message':'read sales rule'}))
```'''
    compute = '''```python
import pandas as pd, json
df = pd.read_csv(BUSINESS_DIR + '/sales.csv')
print(json.dumps({'kind':'final','type':'number','answer':int(df['amount'].sum()),'evidence':'sales.csv amount sum'}))
```'''
    agent = DataMateAgent(
        config={'agent': {'sandbox_timeout_sec': 20, 'max_code_executions': 2},
                'paths': {'work_dir': str(tmp_path / 'work')}},
        data_dir=split, backend=ScriptedBackend([observe, compute]),
    )
    with patch.object(agent.backend, 'generate', wraps=agent.backend.generate) as generate:
        answer, trace = agent.answer_question_with_trace(
            QuestionItem(id='q_test', business_id='biz_test', question='Total amount?', as_of_date='2026-09-07')
        )
    assert 'SUM_AMOUNT_RULE' not in trace['initial_user_prompt']
    assert str(shop) not in trace['initial_user_prompt']
    assert trace['attempts'][0]['parsed_output']['data'] == rules
    assert [a['kind'] for a in trace['attempts']] == ['observation', 'final']
    first, last = [call.args[0][-1]['content'] for call in generate.call_args_list]
    assert 'Đây là lượt cuối' not in first and 'Đây là lượt cuối' in last
    assert answer.type == 'number' and answer.answer == 30
    assert (split / 'rulebook.md').read_text(encoding='utf-8') == rules
