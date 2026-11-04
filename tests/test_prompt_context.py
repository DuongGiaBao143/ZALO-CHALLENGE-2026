"""Short instructions must preserve business evidence and question anchors."""

from src.agent.prompts import (
    SYSTEM_PROMPT,
    build_error_correction_prompt,
    build_observation_prompt,
    build_user_prompt,
)
from src.time_resolver.calendar_utils import load_shared_context


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
    assert '2026-09-06' not in prompt and '2026-09-07' in prompt
    assert prompt.index('How much was sold yesterday?') > prompt.index('README_END')
    assert 'CALENDAR_PATH' in prompt
    assert len(SYSTEM_PROMPT) < 2000


def test_followup_prompts_preserve_observations_errors_and_task():
    observation = build_observation_prompt({'columns': ['order_id']}, 'one row per order', 'Count orders', '2026-09-07')
    correction = build_error_correction_prompt("KeyError: 'amount'", 'runtime_error', 'Count orders', '2026-09-07')
    for prompt in [observation, correction]:
        assert 'Count orders' in prompt and '2026-09-07' in prompt
    assert 'order_id' in observation and 'one row per order' in observation
    assert "KeyError: 'amount'" in correction


def test_full_rulebook_remains_readable_from_runtime_path(tmp_path):
    rules = '# Rules\nGlobal precedence.\n## 1. Sales\nSALES_RULE\n## 2. Debt\nDEBT_RULE\n'
    path = tmp_path / 'rulebook.md'
    path.write_text(rules, encoding='utf-8')
    context = load_shared_context(tmp_path)
    assert context['rulebook_text'] == rules
    assert context['rulebook_path'] == str(path.resolve())
    assert path.read_text(encoding='utf-8') == rules


def test_agent_reads_full_rulebook_via_observation_before_computing(tmp_path):
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
        config={'agent': {'sandbox_timeout_sec': 20}, 'paths': {'work_dir': str(tmp_path / 'work')}},
        data_dir=split, backend=ScriptedBackend([observe, compute]),
    )
    answer, trace = agent.answer_question_with_trace(
        QuestionItem(id='q_test', business_id='biz_test', question='Total amount?', as_of_date='2026-09-07')
    )
    assert 'SUM_AMOUNT_RULE' not in trace['initial_user_prompt']
    assert str(shop) not in trace['initial_user_prompt']
    assert trace['attempts'][0]['parsed_output']['data'] == rules
    assert [a['kind'] for a in trace['attempts']] == ['observation', 'final']
    assert answer.type == 'number' and answer.answer == 30
    assert (split / 'rulebook.md').read_text(encoding='utf-8') == rules
