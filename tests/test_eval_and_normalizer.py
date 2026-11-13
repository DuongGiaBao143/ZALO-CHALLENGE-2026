"""Unit tests for DataMate evaluation scorer, normalizer, and Vietnamese text/date utils."""

import math
import pytest
from src.schemas import AnswerType
from src.postprocess.normalizer import (
    format_answer_payload,
    format_date_value,
    format_number_value,
    format_percent_value,
    normalize_string,
)
from src.postprocess.vn_utils import parse_vn_date, parse_vn_number, vn_norm
from src.eval.scorer import evaluate_predictions, score_single_answer


class TestNormalizer:
    def test_normalize_string_rules(self):
        raw = "  Đậu phộng rang muối (Hộp 500g)!  "
        expected = "đậu phộng rang muối hộp 500g"
        assert normalize_string(raw) == expected

    def test_format_number_integer_and_decimal(self):
        assert format_number_value(48250000) == 48250000
        assert format_number_value("48,250,000") == 48250000
        assert format_number_value(12.345) == 12.35
        assert format_number_value(10.00) == 10

    def test_format_number_rejects_nan_and_inf(self):
        with pytest.raises(ValueError):
            format_number_value(float("nan"))
        with pytest.raises(ValueError):
            format_number_value(float("inf"))

    def test_format_percent_value(self):
        assert format_percent_value("-12.45%") == -12.45
        assert format_percent_value(25.0) == 25
        assert format_percent_value(0.123) == 0.12

    def test_format_date_value_calendar_semantics(self):
        assert format_date_value("2026-08-15") == "2026-08-15"
        assert format_date_value("2026-08") == "2026-08"
        with pytest.raises(ValueError):
            format_date_value("15/08/2026")
        with pytest.raises(ValueError):
            format_date_value("2026-02-31")  # Invalid calendar date

    def test_format_answer_payload_valid_types(self):
        # String
        t, a = format_answer_payload("string", "Cà phê sữa")
        assert t == "string" and a == "Cà phê sữa"

        # String with ISO date -> coerced to date
        t, a = format_answer_payload("string", "2026-05-09")
        assert t == "date" and a == "2026-05-09"

        t, a = format_answer_payload("string", "2025-08")
        assert t == "date" and a == "2025-08"

        # Number
        t, a = format_answer_payload("number", 1000)
        assert t == "number" and a == 1000

        # Unanswerable
        t, a = format_answer_payload("unanswerable", "anything")
        assert t == "unanswerable" and a is None

        # Abstain
        t, a = format_answer_payload("abstain", 123)
        assert t == "abstain" and a is None

        # Boolean
        t, a = format_answer_payload("boolean", "đúng")
        assert t == "boolean" and a is True

        # List
        t, a = format_answer_payload("list", ["Món 1", "Món 2"])
        assert t == "list" and a == ["Món 1", "Món 2"]

        # Table
        t, a = format_answer_payload("table", {"columns": ["A", "B"], "rows": [["x", 1]]})
        assert t == "table" and a["columns"] == ["A", "B"]

        # Table with list of dict rows (auto-converted to list of lists)
        t, a = format_answer_payload("table", {"columns": ["A", "B"], "rows": [{"A": "x", "B": 1}]})
        assert t == "table" and a["rows"] == [["x", 1]]


class TestVnUtils:
    def test_parse_vn_number(self):
        assert parse_vn_number("560,000") == 560000
        assert parse_vn_number("12,500.5đ") == 12500.5
        assert parse_vn_number("1,000,000 VNĐ") == 1000000
        assert math.isnan(parse_vn_number("không rõ"))

    def test_parse_vn_date_mixed(self):
        ts1 = parse_vn_date("1 thg 6 2025")
        assert ts1.strftime("%Y-%m-%d") == "2025-06-01"

        ts2 = parse_vn_date("15/08/2026")
        assert ts2.strftime("%Y-%m-%d") == "2026-08-15"

        ts3 = parse_vn_date("2026-08-27")
        assert ts3.strftime("%Y-%m-%d") == "2026-08-27"


class TestEvaluationScorer:
    def test_score_correct_number(self):
        pred = {"id": "q1", "type": "number", "answer": 50000}
        ref = {"id": "q1", "type": "number", "answer": 50000}
        verdict, score = score_single_answer(pred, ref)
        assert verdict == "correct" and score == 1

    def test_score_wrong_number(self):
        pred = {"id": "q1", "type": "number", "answer": 40000}
        ref = {"id": "q1", "type": "number", "answer": 50000}
        verdict, score = score_single_answer(pred, ref)
        assert verdict == "wrong" and score == -1

    def test_score_abstain(self):
        pred = {"id": "q1", "type": "abstain", "answer": None}
        ref = {"id": "q1", "type": "number", "answer": 50000}
        verdict, score = score_single_answer(pred, ref)
        assert verdict == "abstain" and score == 0

    def test_score_unanswerable_match(self):
        pred = {"id": "q1", "type": "unanswerable", "answer": None}
        ref = {"id": "q1", "type": "unanswerable", "answer": None}
        verdict, score = score_single_answer(pred, ref)
        assert verdict == "correct" and score == 1

    def test_score_unanswerable_when_answered_is_wrong(self):
        pred = {"id": "q1", "type": "number", "answer": 0}
        ref = {"id": "q1", "type": "unanswerable", "answer": None}
        verdict, score = score_single_answer(pred, ref)
        assert verdict == "wrong" and score == -1

    def test_score_string_with_alias(self):
        pred = {"id": "q1", "type": "string", "answer": "SP0001"}
        ref = {"id": "q1", "type": "string", "answer": "Xi măng Hà Tiên PCB40 bao 50kg", "alias": ["SP0001"]}
        verdict, score = score_single_answer(pred, ref)
        assert verdict == "correct" and score == 1

    def test_penalized_accuracy_report(self):
        preds = [
            {"id": "q1", "type": "number", "answer": 10},  # correct (+1)
            {"id": "q2", "type": "abstain", "answer": None},  # abstain (0)
            {"id": "q3", "type": "number", "answer": 99},  # wrong (-1)
        ]
        refs = [
            {"id": "q1", "type": "number", "answer": 10},
            {"id": "q2", "type": "number", "answer": 20},
            {"id": "q3", "type": "number", "answer": 30},
        ]
        rep = evaluate_predictions(preds, refs)
        assert rep.total == 3
        assert rep.correct == 1
        assert rep.abstain == 1
        assert rep.wrong == 1
        assert rep.penalized_accuracy == 0.0
