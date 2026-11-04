import json

from src.agent.prompts import SYSTEM_PROMPT
from src.agent.solver import DataMateAgent, ScriptedBackend
from src.schemas import QuestionItem


def strings_in(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings_in(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings_in(child)


def make_agent(tmp_path, replies):
    split = tmp_path / "split"
    business = split / "data" / "shop"
    business.mkdir(parents=True)
    (business / "orders.csv").write_text("status,qty\ncompleted,2\ncompleted,3\n", encoding="utf-8")
    (split / "rulebook.md").write_text("Count rows for orders; do not count qty.", encoding="utf-8")
    backend = ScriptedBackend(replies)
    config = {"model": {"backend": "scripted"}, "agent": {"max_turns": 3, "sandbox_timeout_sec": 10},
              "paths": {"work_dir": str(tmp_path / "work")}}
    return DataMateAgent(config, split, backend=backend), backend


def test_observation_then_compute_and_full_trace(tmp_path):
    observation = '''MODEL_REPLY_MARKER
```python
df = pd.read_csv(os.path.join(BUSINESS_DIR, 'orders.csv'))
print(json.dumps({'kind':'observation','data':df['status'].unique().tolist(),'message':'observed statuses'}))
```'''
    final = '''FINAL_REPLY_MARKER
```python
df = pd.read_csv(os.path.join(BUSINESS_DIR, 'orders.csv'))
print(json.dumps({'kind':'final','type':'number','answer':int((df['status']=='cancelled').sum()),'evidence':'orders.csv: inspected all statuses, no cancelled rows'}))
```'''
    agent, backend = make_agent(tmp_path, [observation, final])
    answer, trace = agent.answer_question_with_trace(QuestionItem("question1", "shop", "Count cancelled orders", "2026-06-02"))
    assert answer.to_dict() == {"id": "question1", "type": "number", "answer": 0}
    assert backend.idx == 2
    trace_text = json.dumps(trace, ensure_ascii=False)
    assert "MODEL_REPLY_MARKER" in trace_text, "Full successful model reply is required in logs."
    assert SYSTEM_PROMPT in set(strings_in(trace)), "System prompt is required in logs."


def test_invalid_table_triggers_same_model_repair(tmp_path):
    invalid = '''```python
print(json.dumps({'kind':'final','type':'table','answer':{'columns':['name','qty'],'rows':[['Lan']]},'evidence':'orders.csv'}))
```'''
    valid = '''```python
df = pd.read_csv(os.path.join(BUSINESS_DIR, 'orders.csv'))
print(json.dumps({'kind':'final','type':'number','answer':len(df),'evidence':'orders.csv: row count'}))
```'''
    agent, backend = make_agent(tmp_path, [invalid, valid])
    answer, trace = agent.answer_question_with_trace(QuestionItem("question1", "shop", "Count orders", "2026-06-02"))
    assert answer.type == "number" and answer.answer == 2
    assert backend.idx == 2
