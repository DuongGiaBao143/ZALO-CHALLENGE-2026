"""Independent automated tests for P2: Solver Core Rules & Guardrails.

Covers:
- eval_core_rules active by default
- Verified zero acceptance (backed by rows_after_filter > 0 or verified check)
- Rejection of unverified zeros on revenue/sales metrics, falling back to abstain
- Acceptance of zero on unsold / difference metrics without check
- Hallucination blockers:
  - [0, 0] or all-zero lists in debt/movement queries
  - Zero-debt tables
  - Duplicate items in top-k rankings (lists and tables)
- Safe fallback to abstain on unhandled runtime exceptions
- Abstain Gate converting unanswerable to abstain when configured
- Formatted string positive debt acceptance in debt tables
- String zeros list rejection in debt queries
"""

import json
from types import SimpleNamespace
import pandas as pd
import pytest

from src.agent.sandbox import SandboxResult, validate_protocol_payload
from src.agent.solver import BaseInferenceBackend, DataMateAgent
from src.schemas import AnswerType, QuestionItem, SubmissionItem


class ScriptedBackend(BaseInferenceBackend):
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.call_count = 0

    def generate(self, messages):
        if self.call_count < len(self.scripts):
            script = self.scripts[self.call_count]
            self.call_count += 1
            return script
        return "```python\npass\n```"


@pytest.fixture
def test_split(tmp_path):
    split_dir = tmp_path / "test_split"
    biz_dir = split_dir / "data" / "biz_test"
    biz_dir.mkdir(parents=True)
    df = pd.DataFrame({
        "ma_don": ["DH1", "DH2"],
        "ngay": ["2026-05-01", "2026-05-02"],
        "tien": [50000, 100000],
        "trang_thai": ["thanh_cong", "thanh_cong"],
    })
    df.to_csv(biz_dir / "orders.csv", index=False)
    (split_dir / "rulebook.md").write_text("# Rulebook\nQuy tắc chung", encoding="utf-8")
    return split_dir


def test_eval_core_rules_active_by_default(test_split):
    """Verify eval_core_rules defaults to True when initializing DataMateAgent."""
    agent = DataMateAgent(config={}, data_dir=test_split, backend=ScriptedBackend([]))
    assert agent.eval_core_rules is True


def test_verified_zero_accepted(test_split, monkeypatch):
    """Verify answer 0 for revenue is accepted when backed by valid rows_after_filter check."""
    payload = {
        "kind": "final",
        "type": "number",
        "answer": 0,
        "evidence": "Filter matched 5 rows, but all discounts canceled revenue",
        "check": {
            "source_file": "orders.csv",
            "table": "orders",
            "detail": "Đã lọc 5 dòng đơn ngày 2026-05-01, tổng tiền bằng 0",
            "rows_after_filter": 5,
        },
    }
    _, valid_payload = validate_protocol_payload(payload)
    monkeypatch.setattr(
        "src.agent.solver.run_python_in_sandbox",
        lambda **kwargs: SandboxResult(success=True, kind="final", parsed_output=valid_payload),
    )
    agent = DataMateAgent(config={"agent": {"max_turns": 1}}, data_dir=test_split, backend=ScriptedBackend(["```python\npass\n```"]))
    q = QuestionItem("q_vzero", "biz_test", "Tổng doanh thu ngày 2026-05-01 là bao nhiêu?", "2026-05-03")
    ans, trace = agent.answer_question_with_trace(q)

    assert ans.type == "number"
    assert ans.answer == 0
    assert "guard_error" not in trace["attempts"][0]


def test_unverified_zero_rejected_and_falls_back_to_abstain(test_split, monkeypatch):
    """Verify answer 0 for revenue WITHOUT check is rejected by guard and falls back to abstain."""
    unverified_payload = {
        "kind": "final",
        "type": "number",
        "answer": 0,
        "evidence": "orders.csv sum() returned 0",
    }
    _, valid_payload = validate_protocol_payload(unverified_payload)
    monkeypatch.setattr(
        "src.agent.solver.run_python_in_sandbox",
        lambda **kwargs: SandboxResult(success=True, kind="final", parsed_output=valid_payload),
    )
    # max_turns=1: unverified zero fails guard on last turn -> must abstain (0 pts instead of -1 pt)
    agent = DataMateAgent(config={"agent": {"max_turns": 1}}, data_dir=test_split, backend=ScriptedBackend(["```python\npass\n```"]))
    q = QuestionItem("q_unvzero", "biz_test", "Tổng doanh thu ngày 2026-05-01 là bao nhiêu?", "2026-05-03")
    ans, trace = agent.answer_question_with_trace(q)

    assert ans.type == "abstain"
    assert "guard_error" in trace["attempts"][0]
    assert "Kết quả tính ra 0 cho chỉ số doanh thu" in trace["attempts"][0]["guard_error"]


def test_unsold_zero_accepted_without_check(test_split, monkeypatch):
    """Verify metric asking about unsold items (ế) accepts 0 without requiring check."""
    payload = {
        "kind": "final",
        "type": "number",
        "answer": 0,
        "evidence": "Không có mặt hàng nào ế",
    }
    _, valid_payload = validate_protocol_payload(payload)
    monkeypatch.setattr(
        "src.agent.solver.run_python_in_sandbox",
        lambda **kwargs: SandboxResult(success=True, kind="final", parsed_output=valid_payload),
    )
    agent = DataMateAgent(config={"agent": {"max_turns": 1}}, data_dir=test_split, backend=ScriptedBackend(["```python\npass\n```"]))
    q = QuestionItem("q_unsold", "biz_test", "Có bao nhiêu mặt hàng không bán được (ế) trong tháng?", "2026-05-03")
    ans, trace = agent.answer_question_with_trace(q)

    assert ans.type == "number"
    assert ans.answer == 0


def test_hallucination_zero_zero_list_blocked(test_split, monkeypatch):
    """Verify [0, 0] list for debt/payment queries is blocked as hallucination and falls back to abstain."""
    payload = {
        "kind": "final",
        "type": "list",
        "answer": [0, 0],
        "evidence": "Snapshot columns difference is 0",
    }
    _, valid_payload = validate_protocol_payload(payload)
    monkeypatch.setattr(
        "src.agent.solver.run_python_in_sandbox",
        lambda **kwargs: SandboxResult(success=True, kind="final", parsed_output=valid_payload),
    )
    agent = DataMateAgent(config={"agent": {"max_turns": 1}}, data_dir=test_split, backend=ScriptedBackend(["```python\npass\n```"]))
    q = QuestionItem("q_debt", "biz_test", "khách Lan mua chịu thêm nhiêu và trả bớt nợ được bao nhiêu?", "2026-05-03")
    ans, trace = agent.answer_question_with_trace(q)

    assert ans.type == "abstain"
    assert "guard_error" in trace["attempts"][0]
    assert "Danh sách kết quả toàn số 0 ([0, 0] hoặc tương tự)" in trace["attempts"][0]["guard_error"]


def test_hallucination_zero_debt_table_blocked(test_split, monkeypatch):
    """Verify table with all non-positive debt amounts is blocked by guardrail."""
    payload = {
        "kind": "final",
        "type": "table",
        "answer": {
            "columns": ["Khách hàng", "Số tiền nợ"],
            "rows": [["KH01", 0], ["KH02", 0]],
        },
        "evidence": "All customers have 0 remaining debt",
    }
    _, valid_payload = validate_protocol_payload(payload)
    monkeypatch.setattr(
        "src.agent.solver.run_python_in_sandbox",
        lambda **kwargs: SandboxResult(success=True, kind="final", parsed_output=valid_payload),
    )
    agent = DataMateAgent(config={"agent": {"max_turns": 1}}, data_dir=test_split, backend=ScriptedBackend(["```python\npass\n```"]))
    q = QuestionItem("q_table_debt", "biz_test", "bảng top 2 khách còn nợ nhiều nhất?", "2026-05-03")
    ans, trace = agent.answer_question_with_trace(q)

    assert ans.type == "abstain"
    assert "guard_error" in trace["attempts"][0]
    assert "Bảng kết quả công nợ chứa toàn số 0" in trace["attempts"][0]["guard_error"]


def test_hallucination_duplicate_ranking_blocked(test_split, monkeypatch):
    """Verify duplicate entity items in top-k ranking are intercepted and blocked."""
    payload = {
        "kind": "final",
        "type": "list",
        "answer": ["Bánh croissant", "Bánh croissant", "Bánh croissant"],
        "evidence": "Unaggregated line items sorted by quantity",
    }
    _, valid_payload = validate_protocol_payload(payload)
    monkeypatch.setattr(
        "src.agent.solver.run_python_in_sandbox",
        lambda **kwargs: SandboxResult(success=True, kind="final", parsed_output=valid_payload),
    )
    agent = DataMateAgent(config={"agent": {"max_turns": 1}}, data_dir=test_split, backend=ScriptedBackend(["```python\npass\n```"]))
    q = QuestionItem("q_dup_rank", "biz_test", "Top 3 sp bán nhiều nhất tháng 3 năm 2026 là những gì?", "2026-05-03")
    ans, trace = agent.answer_question_with_trace(q)

    assert ans.type == "abstain"
    assert "guard_error" in trace["attempts"][0]
    assert "Danh sách xếp hạng top-k chứa các giá trị/mặt hàng trùng lặp" in trace["attempts"][0]["guard_error"]


def test_unhandled_exception_safe_abstain(test_split):
    """Verify unhandled generator/runtime exceptions cleanly return SubmissionItem.abstain without crashing."""
    class BrokenExceptionBackend(BaseInferenceBackend):
        def generate(self, messages):
            raise MemoryError("Out of Host RAM")

    agent = DataMateAgent(config={}, data_dir=test_split, backend=BrokenExceptionBackend())
    q = QuestionItem("q_crash", "biz_test", "Đếm số đơn", "2026-05-03")
    ans, trace = agent.answer_question_with_trace(q)

    assert ans.type == "abstain"
    assert "Out of Host RAM" in ans.reason
    assert "error" in trace
    assert "Out of Host RAM" in trace["error"]


def test_abstain_on_unanswerable_config_enabled(test_split, monkeypatch):
    """Verify that when abstain_on_unanswerable is True in config, unanswerable is converted to abstain."""
    payload = {
        "kind": "final",
        "type": "unanswerable",
        "answer": None,
        "evidence": "Missing cost column",
        "reason": "Không có dữ liệu giá vốn",
    }
    _, valid_payload = validate_protocol_payload(payload)
    monkeypatch.setattr(
        "src.agent.solver.run_python_in_sandbox",
        lambda **kwargs: SandboxResult(success=True, kind="final", parsed_output=valid_payload),
    )
    agent = DataMateAgent(
        config={"agent": {"abstain_on_unanswerable": True, "max_turns": 1}},
        data_dir=test_split,
        backend=ScriptedBackend(["code"]),
    )
    q = QuestionItem("q_unans_cfg", "biz_test", "Lợi nhuận gộp là bao nhiêu?", "2026-05-03")
    ans, trace = agent.answer_question_with_trace(q)

    assert ans.type == "abstain"


def test_debt_table_with_formatted_string_positive_debt_accepted(test_split, monkeypatch):
    """Verify debt tables with formatted strings for positive debt (e.g. '150,000') are accepted by guard."""
    payload = {
        "kind": "final",
        "type": "table",
        "answer": {
            "columns": ["Khách hàng", "Số tiền nợ"],
            "rows": [["KH01", "150,000"], ["KH02", "250000"]],
        },
        "evidence": "Customer debt calculated from ledger",
    }
    _, valid_payload = validate_protocol_payload(payload)
    monkeypatch.setattr(
        "src.agent.solver.run_python_in_sandbox",
        lambda **kwargs: SandboxResult(success=True, kind="final", parsed_output=valid_payload),
    )
    agent = DataMateAgent(config={"agent": {"max_turns": 1}}, data_dir=test_split, backend=ScriptedBackend(["```python\npass\n```"]))
    q = QuestionItem("q_table_debt_str", "biz_test", "bảng top khách còn nợ nhiều nhất?", "2026-05-03")
    ans, trace = agent.answer_question_with_trace(q)

    assert ans.type == "table"
    assert ans.answer == valid_payload["answer"]
    assert "guard_error" not in trace["attempts"][0]


def test_hallucination_string_zeros_list_blocked(test_split, monkeypatch):
    """Verify string zeros ['0', '0'] or ['0.0', '0.0'] for debt/payment queries are blocked as hallucination."""
    for zero_list in [["0", "0"], ["0.0", "0.0"], ["0,0", "0.00"], [" 0 ", "0"]]:
        payload = {
            "kind": "final",
            "type": "list",
            "answer": zero_list,
            "evidence": "Difference is zero string",
        }
        _, valid_payload = validate_protocol_payload(payload)
        monkeypatch.setattr(
            "src.agent.solver.run_python_in_sandbox",
            lambda **kwargs: SandboxResult(success=True, kind="final", parsed_output=valid_payload),
        )
        agent = DataMateAgent(config={"agent": {"max_turns": 1}}, data_dir=test_split, backend=ScriptedBackend(["```python\npass\n```"]))
        q = QuestionItem("q_debt_str_zero", "biz_test", "khách Lan mua chịu thêm nhiêu và trả bớt nợ được bao nhiêu?", "2026-05-03")
        ans, trace = agent.answer_question_with_trace(q)

        assert ans.type == "abstain", f"Failed to block zero list: {zero_list}"
        assert "guard_error" in trace["attempts"][0]
        assert "Danh sách kết quả toàn số 0 ([0, 0] hoặc tương tự)" in trace["attempts"][0]["guard_error"]


def test_rulebook_in_system_pipeline_keeps_p1_schema_and_p2_guardrails(tmp_path, monkeypatch):
    """Verify baseline rulebook-in-system mode keeps full rulebook in system, zero 'rulebook' in user, P1 schema, and P2 guard."""
    split_dir = tmp_path / "split_rb"
    biz_dir = split_dir / "data" / "biz_rb"
    biz_dir.mkdir(parents=True)
    pd.DataFrame({
        "ma_don": [f"D{i}" for i in range(30)],
        "ngay": ["2026-08-01"] * 30,
        "trang_thai": ["completed"] * 25 + ["returned"] * 5,
        "ma_kh": [f"KH_{i:02d}" for i in range(30)],
        "tien": [100000] * 30,
    }).to_csv(biz_dir / "orders.csv", index=False)
    (biz_dir / "README.md").write_text("Shop quy uoc tinh don hoan thanh.", encoding="utf-8")
    rulebook_body = "# DataMate Rulebook\nDon tinh vao doanh thu la don completed."
    (split_dir / "rulebook.md").write_text(rulebook_body, encoding="utf-8")

    unverified_payload = {
        "kind": "final",
        "type": "number",
        "answer": 0,
        "evidence": "orders.csv sum returned 0",
    }
    _, valid_payload = validate_protocol_payload(unverified_payload)
    monkeypatch.setattr(
        "src.agent.solver.run_python_in_sandbox",
        lambda **kwargs: SandboxResult(success=True, kind="final", parsed_output=valid_payload),
    )
    agent = DataMateAgent(
        config={
            "agent": {
                "eval_core_rules": False,
                "rulebook_in_system": True,
                "use_eval_schema": True,
                "enable_guardrails": True,
                "abstain_on_unanswerable": True,
                "max_turns": 1,
                "max_unique_categorical": 25,
            }
        },
        data_dir=split_dir,
        backend=ScriptedBackend(["```python\npass\n```"]),
    )
    q_zero = QuestionItem("q_rb_01", "biz_rb", "Tổng doanh thu tháng này là bao nhiêu?", "2026-08-10")
    ans, trace = agent.answer_question_with_trace(q_zero)

    sys_msg, user_msg = trace["attempts"][0]["prompt_messages"][:2]
    assert sys_msg["role"] == "system" and rulebook_body in sys_msg["content"]
    assert user_msg["role"] == "user" and "rulebook" not in user_msg["content"].casefold()
    assert "Shop quy uoc tinh don hoan thanh." in user_msg["content"]
    assert "[TOÀN BỘ NHÃN / ALL LABELS (unique=2)] 'trang_thai'" in user_msg["content"]
    assert "[MẪU THAM KHẢO / SAMPLE VALUES (top tần suất, unique=30)] 'ma_kh'" in user_msg["content"]
    assert "2026-08-01 .. 2026-08-10" in user_msg["content"]
    assert ans.type == "abstain"
    assert "guard_error" in trace["attempts"][0]

    q_cmp = QuestionItem("q_rb_02", "biz_rb", "Doanh thu tháng này so với cùng kỳ tháng trước thế nào?", "2026-08-10")
    _, cmp_trace = agent.answer_question_with_trace(q_cmp)
    cmp_sys, cmp_user = cmp_trace["attempts"][0]["prompt_messages"][:2]
    assert cmp_sys["role"] == "system" and rulebook_body in cmp_sys["content"]
    assert cmp_user["role"] == "user" and "rulebook" not in cmp_user["content"].casefold()
    assert "2026-07-01 .. 2026-07-10" in cmp_user["content"]


def test_prompts_keeps_colab_notebook_date_patch_anchor():
    """Verify src/agent/prompts.py preserves the exact date formatting anchor expected by Colab notebooks."""
    from pathlib import Path

    prompts_src = (Path(__file__).resolve().parents[1] / "src" / "agent" / "prompts.py").read_text(encoding="utf-8")
    anchor = '        if matches:\n            dates.append(f"- {label}: {value}")'
    assert prompts_src.count(anchor) == 1
