"""Independent checks for offline initialization, metadata and failure traces."""
import sys
from types import SimpleNamespace

import pytest

from src.agent.prompts import SYSTEM_PROMPT
from src.agent.solver import DataMateAgent, ScriptedBackend, VLLMBackend
from src.schemas import QuestionItem


def all_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_strings(item)


def test_missing_local_weights_never_reaches_vllm_engine(tmp_path, monkeypatch):
    engine_calls = []
    fake_vllm = SimpleNamespace(LLM=lambda **kw: engine_calls.append(kw), SamplingParams=lambda **kw: kw)
    monkeypatch.setitem(sys.modules, "vllm", fake_vllm)
    with pytest.raises(FileNotFoundError):
        VLLMBackend({"local_model_dir": str(tmp_path / "missing"), "name_or_path": "Qwen/Qwen2.5-Coder-7B-Instruct"})
    assert engine_calls == [], "Engine must not be called with a Hub ID as fallback."


@pytest.mark.parametrize("field,value", [("id", "../escape"), ("id", "a/b"), ("as_of_date", "2026-02-31")])
def test_invalid_metadata_is_rejected(field, value):
    row = {"id": "q_safe", "business_id": "shop", "question": "Count orders", "as_of_date": "2026-06-02"}
    row[field] = value
    with pytest.raises(ValueError):
        QuestionItem.from_dict(row)


@pytest.mark.parametrize("setting", ["max_turns", "max_code_executions", "sandbox_timeout_sec"])
def test_zero_execution_limits_fail_before_work(tmp_path, setting):
    with pytest.raises(ValueError):
        DataMateAgent({"agent": {setting: 0}}, tmp_path, backend=ScriptedBackend([]))


def test_model_generation_failure_preserves_context_and_returns_abstain(tmp_path):
    split = tmp_path / "split"
    business = split / "data" / "shop"
    business.mkdir(parents=True)
    (business / "orders.csv").write_text("qty\n1\n", encoding="utf-8")
    (split / "rulebook.md").write_text("RULEBOOK_CONTEXT_MARKER", encoding="utf-8")

    class BrokenBackend:
        def generate(self, messages):
            raise RuntimeError("SIMULATED_ENGINE_ERROR")

    agent = DataMateAgent({"paths": {"work_dir": str(tmp_path / "work")}}, split, backend=BrokenBackend())
    answer, trace = agent.answer_question_with_trace(QuestionItem("q_safe", "shop", "Count orders", "2026-06-02"))
    assert answer.type == "abstain"
    strings = list(all_strings(trace))
    assert SYSTEM_PROMPT in strings
    assert any("SIMULATED_ENGINE_ERROR" in item for item in strings)
    assert 'Count orders' in trace['initial_user_prompt']
    assert 'RULEBOOK_PATH' in trace['initial_user_prompt']
    assert not any("RULEBOOK_CONTEXT_MARKER" in item for item in strings)
    assert agent.shared_context['rulebook_path'] == str((split / 'rulebook.md').resolve())
    assert (split / 'rulebook.md').read_text(encoding='utf-8') == 'RULEBOOK_CONTEXT_MARKER'
