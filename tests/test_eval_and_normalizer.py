"""Unit tests for DataMate string normalization, PA scoring (with `alias`), and Vietnamese utilities."""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

import pandas as pd

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
from src.postprocess.vn_utils import parse_vn_date, parse_vn_number, vn_norm
from src.time_resolver.calendar_utils import resolve_relative_dates


def test_normalize_string_preserves_diacritics_and_strips_punctuation() -> None:
    raw = unicodedata.normalize("NFD", "  Sting - Dâu (330ml)!!  ")
    assert normalize_string(raw) == "sting dâu 330ml"


def test_vn_utils_dates_numbers_and_norm() -> None:
    # 1. Mixed Vietnamese date formats discovered in biz_101 & biz_123
    s_dates = pd.Series(["1 thg 6 2025", "01/01/2025", "2025-08-15", "15/06"])
    parsed = parse_vn_date(s_dates, default_year=2025)
    assert parsed.iloc[0].strftime("%Y-%m-%d") == "2025-06-01"
    assert parsed.iloc[1].strftime("%Y-%m-%d") == "2025-01-01"
    assert parsed.iloc[2].strftime("%Y-%m-%d") == "2025-08-15"
    assert parsed.iloc[3].strftime("%Y-%m-%d") == "2025-06-15"

    # 2. Comma-formatted VND amounts discovered in biz_101/ban_hang.csv
    s_nums = pd.Series(["560,000", "4,000đ", "165,000 VND"])
    parsed_nums = parse_vn_number(s_nums)
    assert list(parsed_nums) == [560000, 4000, 165000]

    # 3. Series NFC normalization
    s_names = pd.Series([unicodedata.normalize("NFD", "Cà Phê Sữa (M)")])
    assert vn_norm(s_names).iloc[0] == "cà phê sữa m"


def test_score_single_answer_with_official_alias_format() -> None:
    # 1. String match with official `alias` field from train/answers.jsonl
    ref_str = {
        "id": "q_06de33fa21cc",
        "type": "string",
        "answer": "Xi măng Hà Tiên PCB40 bao 50kg",
        "alias": ["SP0001"],
    }
    assert score_single_answer(
        {"id": "q_06de33fa21cc", "type": "string", "answer": "sp0001"}, ref_str
    ) == ("correct", 1)
    assert score_single_answer(
        {"id": "q_06de33fa21cc", "type": "string", "answer": "Xi măng Hà Tiên PCB40 bao 50kg"},
        ref_str,
    ) == ("correct", 1)

    # 2. List match with 2D `alias` field from train/answers.jsonl
    ref_list = {
        "id": "q_list",
        "type": "list",
        "answer": ["Cà phê sữa (M)", "Trà đào cam sả (M)", "Cà phê đen (M)"],
        "alias": [["SP0003"], ["SP0017"], ["SP0001"]],
    }
    assert score_single_answer(
        {"id": "q_list", "type": "list", "answer": ["SP0003", "Trà đào cam sả (M)", "sp0001"]},
        ref_list,
    ) == ("correct", 1)

    # 3. Table match with 2D row `alias` field from train/answers.jsonl
    ref_table = {
        "id": "q_0a76d3680594",
        "type": "table",
        "answer": {
            "columns": ["khach_hang", "so_tien_no"],
            "rows": [["Đỗ Đức An", 404500], ["Dương Tâm Bích", 158600]],
        },
        "alias": [["KH0124"], ["KH0233"]],
    }
    pred_table = {
        "id": "q_0a76d3680594",
        "type": "table",
        "answer": {
            "columns": ["khach_hang", "so_tien_no"],
            "rows": [["KH0233", 158600], ["Đỗ Đức An", 404500]],
        },
    }
    assert score_single_answer(pred_table, ref_table) == ("correct", 1)


def test_penalized_accuracy_aggregation() -> None:
    refs = [
        {"id": "1", "type": "number", "answer": 100},
        {"id": "2", "type": "string", "answer": "Xi măng Hà Tiên"},
        {"id": "3", "type": "unanswerable", "answer": None},
        {"id": "4", "type": "boolean", "answer": True},
    ]
    preds = [
        {"id": "1", "type": "number", "answer": 100},
        {"id": "2", "type": "abstain", "answer": None},
        {"id": "3", "type": "number", "answer": 50},
        {"id": "4", "type": "boolean", "answer": True},
    ]
    report = evaluate_predictions(preds, refs)
    assert report.total == 4
    assert report.correct == 2
    assert report.abstain == 1
    assert report.wrong == 1
    assert report.penalized_accuracy == (2 - 1) / 4


def test_resolve_relative_dates() -> None:
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
    test_vn_utils_dates_numbers_and_norm()
    test_score_single_answer_with_official_alias_format()
    test_penalized_accuracy_aggregation()
    test_resolve_relative_dates()
    test_format_answer_payload_fallback_to_abstain()
    print("[OK] All DataMate unit tests (including Vietnamese utilities & alias scoring) passed!")
