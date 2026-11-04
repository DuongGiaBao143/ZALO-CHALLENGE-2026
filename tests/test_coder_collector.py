"""Existing collector and code-filter regressions retained from the archived FSDP tests."""
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock
from src.coder_training.collector import (CandidateCollector, CollectorConfig, CollectorSummary, is_safe_code, compute_provenance_hash)
from src.coder_training.io_utils import select_questions
from src.schemas import QuestionItem, SubmissionItem

class TestCandidateCollector:
    def test_is_safe_code_anti_leak_and_hardcoding(self):
        # 1. Leak answers.jsonl
        leak_code = "import json\nwith open('data/train/answers.jsonl') as f: print(f.read())"
        safe, reason = is_safe_code(leak_code, "q001")
        assert not safe
        assert "forbidden resource" in reason

        # 2. Hardcoded question ID
        hardcoded_code = "import pandas as pd\ndf = pd.read_csv('orders.csv')\n# question q001\nprint('done')"
        safe, reason = is_safe_code(hardcoded_code, "q001")
        assert not safe
        assert "hardcodes question id" in reason

        # 3. Hardcoded generic question pattern
        pattern_code = "import pandas as pd\ndf = pd.read_csv('orders.csv')\n# dev_001_q001 check"
        safe, reason = is_safe_code(pattern_code, "q999")
        assert not safe
        assert "question identifier pattern" in reason

        # 4. Constant answer without data access
        constant_code = 'import json\nprint(json.dumps({"kind": "final", "answer": 120000}))'
        safe, reason = is_safe_code(constant_code, "q001")
        assert not safe
        assert "constant answer" in reason

        # 5. Genuine data access script
        valid_code = (
            "import os, json, pandas as pd\n"
            "df = pd.read_csv(os.path.join(BUSINESS_DIR, 'banh_mi.csv'))\n"
            "res = int(df['tien'].sum())\n"
            'print(json.dumps({"kind": "final", "type": "number", "answer": res}))\n'
        )
        safe, reason = is_safe_code(valid_code, "q001")
        assert safe
        assert reason == "ok"

    def test_sft_extraction_only_from_correct_trajectories(self, tmp_path):
        mock_agent = MagicMock()
        mock_agent.data_dir = tmp_path / 'raw'
        mock_agent.data_dir.mkdir()
        mock_agent.config = {}
        mock_gold = {"q001": {"id": "q001", "type": "number", "answer": 100}}
        config = CollectorConfig(output_dir=str(tmp_path / "sft"), cache_dir=str(tmp_path / "cache"))
        collector = CandidateCollector(agent=mock_agent, config=config, gold_answers=mock_gold)

        item = QuestionItem(id="q001", business_id="biz_A", question="Doanh thu?", as_of_date="2026-08-27")
        summary = CollectorSummary()

        # Case A: Trajectory with wrong final verdict -> MUST NOT extract any steps
        wrong_trace = {
            "attempts": [
                {
                    "success": True,
                    "kind": "final",
                    "generated_code": "import pandas as pd\ndf = pd.read_csv('data.csv')\nprint('ok')",
                    "prompt_messages": [{"role": "user", "content": "prompt"}],
                    "llm_reply": "reply",
                }
            ]
        }
        res_wrong = collector.extract_sft_examples_from_trace(item, wrong_trace, verdict="wrong", summary=summary)
        assert len(res_wrong) == 0
        assert summary.rejected_reasons.get("final_answer_not_correct") == 1

        # Case B: Trajectory with correct final verdict:
        # Step 1: execution error (kept in prompt history for self-correction, but NOT target)
        # Step 2: successful final step (IS target)
        correct_trace = {
            "attempts": [
                {
                    "turn": 1,
                    "success": False,
                    "kind": "error",
                    "generated_code": "import pandas as pd\nraise ValueError('error')",
                    "prompt_messages": [{"role": "user", "content": "prompt turn 1"}],
                    "llm_reply": "bad code",
                },
                {
                    "turn": 2,
                    "success": True,
                    "kind": "final",
                    "generated_code": (
                        "import os, json, pandas as pd\n"
                        "df = pd.read_csv(os.path.join(BUSINESS_DIR, 'sales.csv'))\n"
                        'print(json.dumps({"kind": "final", "answer": 100}))'
                    ),
                    "prompt_messages": [
                        {"role": "user", "content": "prompt turn 1"},
                        {"role": "assistant", "content": "bad code"},
                        {"role": "user", "content": "fix error"},
                    ],
                    "llm_reply": "good code",
                },
            ]
        }
        res_correct = collector.extract_sft_examples_from_trace(item, correct_trace, verdict="correct", summary=summary)
        assert len(res_correct) == 1
        assert res_correct[0]["turn"] == 2
        assert res_correct[0]["target_completion"] == "good code"
        assert res_correct[0]["provenance"] == "execution-verified pseudo-label"


@pytest.mark.parametrize('code', [
    '# read_csv(BUSINESS_DIR)\nprint(7)', 's = "pd.read_excel(Path(BUSINESS_DIR))"\nprint(7)',
    'from pathlib import Path\np = Path(BUSINESS_DIR)\nprint(7)',
    'print(7)', 'bad python ++'])
def test_comment_or_string_is_not_data_access(code):
    assert not is_safe_code(code, 'qid')[0]


def test_cache_rescores_gold_and_tracks_context(tmp_path):
    raw = tmp_path / 'raw'
    raw.mkdir()
    (raw / 'rulebook.md').write_text('v1')
    item = QuestionItem(id='q_a', business_id='biz_a', question='sum?', as_of_date='2026-01-01')
    calls = []
    sub = SubmissionItem(id=item.id, type='number', answer=7, evidence='csv')
    agent = SimpleNamespace(data_dir=raw, config={}, answer_question_with_trace=lambda q: (calls.append(q) or sub, {}))
    cfg = CollectorConfig(output_dir=str(tmp_path / 'out'), cache_dir=str(tmp_path / 'cache'))
    golds = {item.id: dict(id=item.id, type='number', answer=7)}
    collector = CandidateCollector(agent, cfg, golds)
    assert collector._run_or_resume_question(item)[2] == 'correct'
    golds[item.id]['answer'] = 8
    assert collector._run_or_resume_question(item)[2] == 'wrong'
    assert len(calls) == 1
    (raw / 'rulebook.md').write_text('v2')
    CandidateCollector(agent, cfg, golds)._run_or_resume_question(item)
    assert len(calls) == 2
    golds.clear()
    with pytest.raises(ValueError, match='Missing gold'):
        collector._run_or_resume_question(item)


def test_provenance_covers_generation_budget():
    item = QuestionItem(id='q_a', business_id='biz_a', question='sum?', as_of_date='2026-01-01')
    a = compute_provenance_hash(item, 'base', {'model': {'max_tokens': 20}})
    b = compute_provenance_hash(item, 'base', {'model': {'max_tokens': 21}})
    assert a != b


def test_pilot_balances_businesses_deterministically():
    rows = [QuestionItem(id=f'q_{b}_{i}', business_id=f'biz_{b}', question='?', as_of_date='2026-01-01')
            for b in range(6) for i in range(20)]
    selected = select_questions(rows, 12, seed=42)
    assert len({q.business_id for q in selected}) == 6
    assert [q.id for q in selected] == [q.id for q in select_questions(rows, 12, seed=42)]
    assert len(select_questions(rows, None)) == 120

