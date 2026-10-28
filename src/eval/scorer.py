"""Official Penalized Accuracy (PA) scorer matching `evaluation.md`.

Scoring rules:
  - `abstain` (or missing answer) -> 0 points
  - `correct` -> +1 point
  - `wrong` -> -1 point
  PA = (1 / N) * sum(s_i)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from src.postprocess.normalizer import (
    format_number_value,
    format_percent_value,
    normalize_string,
)
from src.schemas import AnswerType


def _match_number(pred: Any, ref: Any) -> bool:
    try:
        p = format_number_value(pred)
        r = format_number_value(ref)
        return round(float(p), 2) == round(float(r), 2)
    except Exception:
        return False


def _match_percent(pred: Any, ref: Any) -> bool:
    try:
        p = format_percent_value(pred)
        r = format_percent_value(ref)
        return round(float(p), 2) == round(float(r), 2)
    except Exception:
        return False


def _match_string(pred: Any, ref: Union[str, Sequence[str]]) -> bool:
    """Match normalized string against reference or list of accepted reference forms."""
    if pred is None:
        return False
    norm_pred = normalize_string(pred)
    if not norm_pred:
        return False

    if isinstance(ref, (list, tuple, set)):
        accepted_forms = {normalize_string(x) for x in ref}
    else:
        accepted_forms = {normalize_string(ref)}

    return norm_pred in accepted_forms


def _match_cell(pred_cell: Any, ref_cell: Any) -> bool:
    """Match an element/cell using the number rule (if numeric) or string rule."""
    if isinstance(ref_cell, (int, float)) and not isinstance(ref_cell, bool):
        return _match_number(pred_cell, ref_cell)
    return _match_string(pred_cell, ref_cell)


def _match_list(pred: Any, ref: Any) -> bool:
    """Always ordered, matched position by position with string or number rule."""
    if not isinstance(pred, list) or not isinstance(ref, list):
        return False
    if len(pred) != len(ref):
        return False
    return all(_match_cell(p_item, r_item) for p_item, r_item in zip(pred, ref))


def _canonical_cell(cell: Any, is_numeric_col: bool) -> Any:
    if is_numeric_col:
        try:
            return round(float(format_number_value(cell)), 2)
        except Exception:
            return ("__invalid_num__", str(cell))
    if isinstance(cell, (list, tuple, set)):
        # If reference cell has multiple accepted forms, pick sorted tuple of normalized forms
        return tuple(sorted(normalize_string(x) for x in cell))
    return normalize_string(cell)


def _match_table(pred: Any, ref: Any) -> bool:
    """Match table according to evaluation.md:
    - Columns are matched by normalized name; if names do not match, by position.
    - Rows are matched as a set; name cells with string rule, numeric cells with number rule.
    """
    if not isinstance(pred, dict) or not isinstance(ref, dict):
        return False
    pred_cols = pred.get("columns")
    pred_rows = pred.get("rows")
    ref_cols = ref.get("columns")
    ref_rows = ref.get("rows")

    if not isinstance(pred_cols, list) or not isinstance(pred_rows, list):
        return False
    if not isinstance(ref_cols, list) or not isinstance(ref_rows, list):
        return False
    if len(pred_cols) != len(ref_cols) or len(pred_rows) != len(ref_rows):
        return False

    norm_pred_cols = [normalize_string(c) for c in pred_cols]
    norm_ref_cols = [normalize_string(c) for c in ref_cols]

    # Determine column permutation mapping ref column idx -> pred column idx
    if set(norm_pred_cols) == set(norm_ref_cols) and len(set(norm_ref_cols)) == len(norm_ref_cols):
        col_map = [norm_pred_cols.index(rc) for rc in norm_ref_cols]
    else:
        col_map = list(range(len(ref_cols)))

    # Reorder pred_rows to match ref_cols order
    reordered_pred_rows: List[List[Any]] = []
    for row in pred_rows:
        if not isinstance(row, (list, tuple)) or len(row) != len(ref_cols):
            return False
        reordered_pred_rows.append([row[idx] for idx in col_map])

    # Match rows as a set (bipartite / multiset matching)
    used_pred = [False] * len(reordered_pred_rows)
    for r_row in ref_rows:
        if not isinstance(r_row, (list, tuple)) or len(r_row) != len(ref_cols):
            return False
        matched_idx = None
        for p_idx, p_row in enumerate(reordered_pred_rows):
            if used_pred[p_idx]:
                continue
            if all(_match_cell(p_cell, r_cell) for p_cell, r_cell in zip(p_row, r_row)):
                matched_idx = p_idx
                break
        if matched_idx is None:
            return False
        used_pred[matched_idx] = True

    return True


def score_single_answer(
    pred_item: Optional[Dict[str, Any]],
    ref_item: Dict[str, Any],
) -> Tuple[str, int]:
    """Score a single prediction against a reference item.

    Returns:
        (verdict, score) where verdict in {"correct", "abstain", "wrong"}
        and score in {1, 0, -1}.
    """
    if pred_item is None:
        return "abstain", 0

    pred_type = str(pred_item.get("type", "")).strip().lower()
    if not pred_type or pred_type == AnswerType.ABSTAIN.value:
        return "abstain", 0

    ref_type = str(ref_item.get("type", "")).strip().lower()
    if pred_type != ref_type:
        return "wrong", -1

    pred_ans = pred_item.get("answer")
    # Support optional `accepted_forms` field in reference item for strings
    ref_ans = ref_item.get("accepted_forms", ref_item.get("answer"))

    if ref_type == AnswerType.UNANSWERABLE.value:
        return "correct", 1

    if ref_type == AnswerType.NUMBER.value:
        is_ok = _match_number(pred_ans, ref_ans)
    elif ref_type == AnswerType.PERCENT.value:
        is_ok = _match_percent(pred_ans, ref_ans)
    elif ref_type == AnswerType.STRING.value:
        is_ok = _match_string(pred_ans, ref_ans)
    elif ref_type == AnswerType.DATE.value:
        is_ok = str(pred_ans).strip() == str(ref_ans).strip()
    elif ref_type == AnswerType.BOOLEAN.value:
        is_ok = isinstance(pred_ans, bool) and (pred_ans == bool(ref_ans))
    elif ref_type == AnswerType.LIST.value:
        is_ok = _match_list(pred_ans, ref_ans)
    elif ref_type == AnswerType.TABLE.value:
        is_ok = _match_table(pred_ans, ref_ans)
    else:
        is_ok = False

    return ("correct", 1) if is_ok else ("wrong", -1)


@dataclass
class EvaluationReport:
    """Summary of Penalized Accuracy (PA) across a dataset split."""

    total: int
    correct: int
    abstain: int
    wrong: int
    penalized_accuracy: float
    by_type: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def format_summary(self) -> str:
        lines = [
            "=" * 60,
            "ZALO AI CHALLENGE 2026 — DATAMATE EVALUATION REPORT",
            "=" * 60,
            f"Total Questions (N)    : {self.total}",
            f"  [+] Correct (+1 pt)  : {self.correct} ({self.correct / max(1, self.total):.1%})",
            f"  [0] Abstain ( 0 pt)  : {self.abstain} ({self.abstain / max(1, self.total):.1%})",
            f"  [-] Wrong   (-1 pt)  : {self.wrong} ({self.wrong / max(1, self.total):.1%})",
            "-" * 60,
            f"PENALIZED ACCURACY (PA): {self.penalized_accuracy:.4f}",
            "=" * 60,
        ]
        if self.by_type:
            lines.append("Breakdown by Reference Type:")
            for rtype, counts in sorted(self.by_type.items()):
                n_t = counts["total"]
                pa_t = (counts["correct"] - counts["wrong"]) / max(1, n_t)
                lines.append(
                    f"  - {rtype:<13}: N={n_t:<4} | "
                    f"Correct={counts['correct']:<4} | "
                    f"Abstain={counts['abstain']:<4} | "
                    f"Wrong={counts['wrong']:<4} | PA={pa_t:+.4f}"
                )
            lines.append("=" * 60)
        return "\n".join(lines)


def evaluate_predictions(
    predictions: Iterable[Dict[str, Any]],
    references: Iterable[Dict[str, Any]],
) -> EvaluationReport:
    """Compute Penalized Accuracy (PA) over all reference items."""
    pred_map = {str(item["id"]): item for item in predictions if "id" in item}
    ref_list = list(references)

    counts = Counter()
    by_type: Dict[str, Dict[str, int]] = {}
    total_score = 0

    for ref_item in ref_list:
        qid = str(ref_item["id"])
        ref_type = str(ref_item.get("type", "unknown")).strip().lower()
        pred_item = pred_map.get(qid)

        verdict, score = score_single_answer(pred_item, ref_item)
        counts[verdict] += 1
        total_score += score

        if ref_type not in by_type:
            by_type[ref_type] = {"total": 0, "correct": 0, "abstain": 0, "wrong": 0}
        by_type[ref_type]["total"] += 1
        by_type[ref_type][verdict] += 1

    total = len(ref_list)
    pa = total_score / total if total > 0 else 0.0
    return EvaluationReport(
        total=total,
        correct=counts["correct"],
        abstain=counts["abstain"],
        wrong=counts["wrong"],
        penalized_accuracy=pa,
        by_type=by_type,
    )
