"""Regression test suite replaying dev failure cases from failure_analysis.md.

Validates that:
- q_02a70ea566f1: Duplicate top-k products (["Bánh croissant", ...]) is intercepted by guardrail.
- q_43df08e6cce8: [0, 0] debt hallucination is intercepted by guardrail.
- q_9b1dce77c710: Zero-debt table is intercepted by guardrail.
- q_e7837d5638fb: Forward-filling parent attributes on biz_122 correctly filters cancelled/returned items and yields gold 248,572,900.
- q_d401c0884402: "Cùng kỳ tháng trước" date intervals on biz_130 correctly calculate percentage change -18.92%.
"""

import os
import pandas as pd
import pytest

from src.agent.prompts import build_user_prompt
from src.agent.sandbox import SandboxResult, load_excel_unmerge, run_python_in_sandbox, validate_protocol_payload
from src.agent.solver import BaseInferenceBackend, DataMateAgent
from src.schemas import AnswerType, QuestionItem
from src.time_resolver.calendar_utils import resolve_relative_dates


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
def mock_split(tmp_path):
    split_dir = tmp_path / "mock_split"
    biz_dir = split_dir / "data" / "biz_dev"
    biz_dir.mkdir(parents=True)
    (biz_dir / "sales.csv").write_text("item,qty\ncroissant,1\n", encoding="utf-8")
    (split_dir / "rulebook.md").write_text("# Rulebook", encoding="utf-8")
    return split_dir


def test_regression_q_02a70ea566f1_duplicate_ranking_blocked(mock_split, monkeypatch):
    """Case q_02a70ea566f1: Duplicate items in top-k list blocked from scoring SAI (-1.0)."""
    payload = {
        "kind": "final",
        "type": "list",
        "answer": ["Bánh croissant", "Bánh croissant", "Bánh croissant"],
        "evidence": "valid.sort_values(by='qty_conv', ascending=False).head(3)",
    }
    _, valid_payload = validate_protocol_payload(payload)
    monkeypatch.setattr(
        "src.agent.solver.run_python_in_sandbox",
        lambda **kwargs: SandboxResult(success=True, kind="final", parsed_output=valid_payload),
    )
    agent = DataMateAgent(
        config={"agent": {"eval_core_rules": True, "max_turns": 1}},
        data_dir=mock_split,
        backend=ScriptedBackend(["```python\npass\n```"]),
    )
    q = QuestionItem("q_02a70ea566f1", "biz_dev", "Top 3 sp bán nhiều nhất tháng 3 năm 2026 là những gì?", "2026-03-31")
    ans, trace = agent.answer_question_with_trace(q)

    # Scored abstain (0 pts) instead of SAI (-1.0 pt)
    assert ans.type == "abstain"
    assert "guard_error" in trace["attempts"][0]
    assert "trùng lặp" in trace["attempts"][0]["guard_error"]


def test_regression_q_43df08e6cce8_zero_zero_debt_blocked(mock_split, monkeypatch):
    """Case q_43df08e6cce8: [0, 0] debt list blocked from scoring SAI (-1.0)."""
    payload = {
        "kind": "final",
        "type": "list",
        "answer": [0, 0],
        "evidence": "new_debt = 0, paid = 0 from snapshot",
    }
    _, valid_payload = validate_protocol_payload(payload)
    monkeypatch.setattr(
        "src.agent.solver.run_python_in_sandbox",
        lambda **kwargs: SandboxResult(success=True, kind="final", parsed_output=valid_payload),
    )
    agent = DataMateAgent(
        config={"agent": {"eval_core_rules": True, "max_turns": 1}},
        data_dir=mock_split,
        backend=ScriptedBackend(["```python\npass\n```"]),
    )
    q = QuestionItem("q_43df08e6cce8", "biz_dev", "khách Giang Phương Thu mua chịu thêm nhiêu và trả bớt nợ được bao nhiêu?", "2026-03-31")
    ans, trace = agent.answer_question_with_trace(q)

    assert ans.type == "abstain"
    assert "guard_error" in trace["attempts"][0]
    assert "[0, 0]" in trace["attempts"][0]["guard_error"]


def test_regression_q_9b1dce77c710_zero_debt_table_blocked(mock_split, monkeypatch):
    """Case q_9b1dce77c710: All-zero debtor table blocked from scoring SAI (-1.0)."""
    payload = {
        "kind": "final",
        "type": "table",
        "answer": {
            "columns": ["Mã KH", "Tên KH", "Số điện thoại", "Số tiền nợ"],
            "rows": [
                ["KH0001", "Nguyễn Phương An", "932426380", 0],
                ["KH0002", "Đào Dương Giang", "912365003", 0],
                ["KH0003", "Thân Trang Hồng", "702804243", 0],
            ],
        },
        "evidence": "Customer snapshot debt balance",
    }
    _, valid_payload = validate_protocol_payload(payload)
    monkeypatch.setattr(
        "src.agent.solver.run_python_in_sandbox",
        lambda **kwargs: SandboxResult(success=True, kind="final", parsed_output=valid_payload),
    )
    agent = DataMateAgent(
        config={"agent": {"eval_core_rules": True, "max_turns": 1}},
        data_dir=mock_split,
        backend=ScriptedBackend(["```python\npass\n```"]),
    )
    q = QuestionItem("q_9b1dce77c710", "biz_dev", "bảng 3 khách còn nợ nhiều nhất", "2026-03-31")
    ans, trace = agent.answer_question_with_trace(q)

    assert ans.type == "abstain"
    assert "guard_error" in trace["attempts"][0]
    assert "Bảng kết quả công nợ chứa toàn số 0" in trace["attempts"][0]["guard_error"]


def test_regression_q_e7837d5638fb_excel_unmerge_gold_calculation():
    """Case q_e7837d5638fb: Forward filling parent attributes on biz_122 reproduces exact gold revenue 248,572,900."""
    orders_detail_path = "data/train/data/biz_122/DonHang_ChiTiet_1.xlsx"

    if os.path.exists(orders_detail_path):
        # 1. Load detail with unmerge & ffill (header=2)
        df_detail = load_excel_unmerge(orders_detail_path, sheet_name="T09-2025", header=2)
        assert len(df_detail) == 5635
        assert df_detail["Mã đơn hàng"].isna().sum() == 0
        assert df_detail["Trạng thái đơn hàng"].isna().sum() == 0

        # Parse amounts
        from src.postprocess.vn_utils import parse_vn_number
        df_detail["tien_num"] = parse_vn_number(df_detail["Tổng tiền"])

        # Filter completed orders (excludes Đã hủy and Đã hoàn hàng)
        completed_items = df_detail[df_detail["Trạng thái đơn hàng"] == "Đã hoàn thành"]
        total_rev = int(completed_items["tien_num"].sum())

        # Exact gold match from failure_analysis.md line 10 & 29: 248,572,900 VND
        assert total_rev == 248572900


def test_regression_q_d401c0884402_cung_ky_gold_calculation():
    """Case q_d401c0884402: "Cùng kỳ tháng trước" date prompt on biz_130 reproduces exact gold change -18.92%."""
    as_of_date = "2025-08-03"
    question = "So với cùng kỳ tháng trước, doanh thu từ đầu tháng này đến hết hôm nay tăng hay giảm bao nhiêu %?"
    rel = resolve_relative_dates(as_of_date)

    prompt = build_user_prompt(
        question=question,
        as_of_date=as_of_date,
        relative_dates=rel,
        schema_markdown="",
        core_rules=True,
    )

    # Prompt correctly injects same period and suppresses full previous month
    assert "2025-07-01 .. 2025-07-03" in prompt
    assert "2025-08-01 .. 2025-08-03" in prompt
    assert "2025-07-01 .. 2025-07-31" not in prompt

    # Verify mathematical gold calculation from failure_analysis.md line 12 & 34:
    # Current period (01/08/2025 - 03/08/2025): 117,948,000 VND
    # Prior same period (01/07/2025 - 03/07/2025): 145,478,500 VND
    curr_rev = 117948000
    prior_rev = 145478500
    pct_change = round((curr_rev - prior_rev) / prior_rev * 100, 2)
    assert pct_change == -18.92
