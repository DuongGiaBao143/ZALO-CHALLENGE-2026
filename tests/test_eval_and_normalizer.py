"""Unit tests for DataMate string normalization, PA scoring, and date resolution."""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.eval.scorer import evaluate_predictions, score_single_answer
from src.postprocess.normalizer import (
    format_answer_payload,
    format_number_value,
    format_percent_value,
    normalize_string,
)
from src.time_resolver.calendar_utils import resolve_relative_dates


def test_normalize_string_preserves_diacritics_and_strips_punctuation() -> None:
    # Decomposed NFD string + punctuation + extra spaces
    raw = unicodedata.normalize("NFD", "  Sting - Dâu (330ml)!!  ")
    assert normalize_string(raw) == "sting dâu 330ml"


def test_score_single_answer_types() -> None:
    # 1. String match with accepted forms (name + code)
    ref_str = {
        "id": "q1",
        "type": "string",
        "accepted_forms": ["Sting dâu 330ml", "SP0042"],
    }
    assert score_single_answer({"id": "q1", "type": "string", "answer": "  sp0042 "}, ref_str) == (
        "correct",
        1,
    )
    assert score_single_answer(
        {"id": "q1", "type": "string", "answer": "Sting dâu  330ML!"}, ref_str
    ) == ("correct", 1)
    assert score_single_answer({"id": "q1", "type": "string", "answer": "Pepsi"}, ref_str) == (
        "wrong",
        -1,
    )

    # 2. Number & Percent
    ref_num = {"id": "q2", "type": "number", "answer": 48250000}
    assert score_single_answer({"id": "q2", "type": "number", "answer": 48250000.0}, ref_num) == (
        "correct",
        1,
    )
    ref_pct = {"id": "q3", "type": "percent", "answer": -12.45}
    assert score_single_answer({"id": "q3", "type": "percent", "answer": -12.454}, ref_pct) == (
        "correct",
        1,
    )
    assert score_single_answer({"id": "q3", "type": "percent", "answer": 12.45}, ref_pct) == (
        "wrong",
        -1,
    )

    # 3. List (ordered)
    ref_list = {"id": "q4", "type": "list", "answer": ["Cà phê sữa", "Bạc xỉu", "Trà đào"]}
    assert score_single_answer(
        {"id": "q4", "type": "list", "answer": ["cà phê sữa", "BẠC XỈU", "trà đào"]},
        ref_list,
    ) == ("correct", 1)
    assert score_single_answer(
        {"id": "q4", "type": "list", "answer": ["Bạc xỉu", "Cà phê sữa", "Trà đào"]},
        ref_list,
    ) == ("wrong", -1)

    # 4. Table (columns matched by normalized name, rows matched as a set)
    ref_table = {
        "id": "q5",
        "type": "table",
        "answer": {
            "columns": ["Sản phẩm", "Doanh thu"],
            "rows": [["Trà đào", 150000], ["Cà phê sữa", 300000]],
        },
    }
    pred_table_reordered = {
        "id": "q5",
        "type": "table",
        "answer": {
            "columns": ["doanh thu", "SẢN PHẨM"],
            "rows": [[300000, "cà phê sữa"], [150000, "Trà Đào"]],
        },
    }
    assert score_single_answer(pred_table_reordered, ref_table) == ("correct", 1)

    # 5. Unanswerable & Abstain
    ref_unans = {"id": "q6", "type": "unanswerable", "answer": None}
    assert score_single_answer({"id": "q6", "type": "unanswerable"}, ref_unans) == ("correct", 1)
    assert score_single_answer({"id": "q6", "type": "number", "answer": 0}, ref_unans) == (
        "wrong",
        -1,
    )
    assert score_single_answer({"id": "q6", "type": "abstain"}, ref_unans) == ("abstain", 0)


def test_penalized_accuracy_aggregation() -> None:
    refs = [
        {"id": "1", "type": "number", "answer": 100},
        {"id": "2", "type": "string", "answer": "Xi măng Hà Tiên"},
        {"id": "3", "type": "unanswerable", "answer": None},
        {"id": "4", "type": "boolean", "answer": True},
    ]
    preds = [
        {"id": "1", "type": "number", "answer": 100},  # +1 (correct)
        {"id": "2", "type": "abstain", "answer": None},  #  0 (abstain)
        {"id": "3", "type": "number", "answer": 50},  # -1 (wrong on unanswerable)
        {"id": "4", "type": "boolean", "answer": True},  # +1 (correct)
    ]
    report = evaluate_predictions(preds, refs)
    assert report.total == 4
    assert report.correct == 2
    assert report.abstain == 1
    assert report.wrong == 1
    assert report.penalized_accuracy == (2 - 1) / 4


def test_resolve_relative_dates() -> None:
    # 2026-03-04 is a Wednesday
    rel = resolve_relative_dates("2026-03-04")
    assert rel["as_of_date (hôm nay / today)"] == "2026-03-04"
    assert rel["tuần rồi / tuần trước (last week, Mon-Sun)"] == "2026-02-23 .. 2026-03-01"


def test_format_answer_payload_fallback_to_abstain() -> None:
    t, ans = format_answer_payload("number", "not_a_number", fallback_to_abstain=True)
    assert t == "abstain"
    assert ans is None
    assert format_number_value("48,250,000.00") == 48250000
    assert format_percent_value("-12.456%") == -12.46


if __name__ == "__main__":
    test_normalize_string_preserves_diacritics_and_strips_punctuation()
    test_score_single_answer_types()
    test_penalized_accuracy_aggregation()
    test_resolve_relative_dates()
    test_format_answer_payload_fallback_to_abstain()
    print("[OK] All DataMate unit tests passed successfully!")

