"""Official Penalized Accuracy (PA) evaluation engine for local benchmarking."""

from .scorer import EvaluationReport, evaluate_predictions, score_single_answer

__all__ = ["score_single_answer", "evaluate_predictions", "EvaluationReport"]
