"""Metric evaluation wrapper providing evaluate_records for evaluation notebooks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
from src.eval.scorer import evaluate_predictions, EvaluationReport


@dataclass
class MetricSummary:
    num_correct: int
    num_wrong: int
    num_abstained: int
    total: int
    penalized_accuracy: float
    accuracy: float
    abstain_rate: float
    report: EvaluationReport

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "correct": self.num_correct,
            "num_correct": self.num_correct,
            "wrong": self.num_wrong,
            "num_wrong": self.num_wrong,
            "abstain": self.num_abstained,
            "num_abstained": self.num_abstained,
            "penalized_accuracy": self.penalized_accuracy,
            "accuracy": self.accuracy,
            "abstain_rate": self.abstain_rate,
        }


def evaluate_records(
    references: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
) -> MetricSummary:
    """Compute Penalized Accuracy and return structured MetricSummary."""
    report = evaluate_predictions(predictions=predictions, references=references)
    total = max(1, report.total)
    return MetricSummary(
        num_correct=report.correct,
        num_wrong=report.wrong,
        num_abstained=report.abstain,
        total=report.total,
        penalized_accuracy=report.penalized_accuracy,
        accuracy=report.correct / total,
        abstain_rate=report.abstain / total,
        report=report,
    )
