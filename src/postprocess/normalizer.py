"""Exact implementation of normalization and formatting rules from evaluation.md.

Normalization rules for `string`:
  (1) Unicode NFC
  (2) lowercase
  (3) every character that is not a letter, a digit or whitespace is replaced by a space
  (4) leading/trailing whitespace removed and runs of whitespace collapsed to one space
  * Diacritics are NOT removed.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime
from typing import Any, Tuple

from src.schemas import AnswerType, VALID_ANSWER_TYPES

_WHITESPACE_RE = re.compile(r"\s+")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_ISO_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def normalize_string(text: Any) -> str:
    """Normalize a string according to the official DataMate evaluation rule.

    Steps:
      1. Convert to Unicode NFC
      2. Convert to lowercase
      3. Replace any character that is not a letter, digit, or whitespace with a space
      4. Strip leading/trailing whitespace and collapse multiple spaces to one space
    Vietnamese diacritics are preserved.
    """
    if text is None:
        return ""
    s = str(text)
    # (1) Unicode NFC
    s = unicodedata.normalize("NFC", s)
    # (2) lowercase
    s = s.lower()
    # (3) every character that is not a letter, a digit or whitespace -> space
    chars = []
    for ch in s:
        if ch.isalpha() or ch.isdigit() or ch.isspace():
            chars.append(ch)
        else:
            chars.append(" ")
    s = "".join(chars)
    # (4) strip and collapse runs of whitespace to one space
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


def format_number_value(value: Any) -> int | float:
    """Format numeric value: integer if whole number, else rounded to 2 decimals."""
    if isinstance(value, bool):
        raise ValueError("Boolean is not a valid numeric value.")
    if isinstance(value, (dict, list)):
        raise ValueError(f"Collection type {type(value).__name__} is not a valid numeric value.")
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        num = float(cleaned)
    else:
        num = float(value)

    if math.isnan(num) or math.isinf(num):
        raise ValueError("NaN or Inf is not a valid number.")

    rounded = round(num, 2)
    if rounded.is_integer():
        return int(round(rounded))
    return rounded


def format_percent_value(value: Any) -> float | int:
    """Format percentage value: rounded to 2 decimal places, preserving sign."""
    if isinstance(value, bool):
        raise ValueError("Boolean is not a valid percent value.")
    if isinstance(value, (dict, list)):
        raise ValueError(f"Collection type {type(value).__name__} is not a valid percent value.")
    if isinstance(value, str):
        cleaned = value.strip().rstrip("%").strip().replace(",", "")
        num = float(cleaned)
    else:
        num = float(value)

    if math.isnan(num) or math.isinf(num):
        raise ValueError("NaN or Inf is not a valid percent.")

    rounded = round(num, 2)
    if rounded.is_integer():
        return int(round(rounded))
    return rounded


def format_date_value(value: Any) -> str:
    """Validate and format ISO date (`yyyy-mm-dd`) or ISO month (`yyyy-mm`) with calendar semantics."""
    if value is None:
        raise ValueError("Date cannot be None.")
    s = str(value).strip()

    # Day format YYYY-MM-DD
    if _ISO_DATE_RE.match(s):
        try:
            parsed = datetime.strptime(s, "%Y-%m-%d")
            if parsed.strftime("%Y-%m-%d") != s:
                raise ValueError
            return s
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid calendar date: {s!r}") from exc

    # Month format YYYY-MM
    if _ISO_MONTH_RE.match(s):
        try:
            parsed = datetime.strptime(s, "%Y-%m")
            if parsed.strftime("%Y-%m") != s:
                raise ValueError
            return s
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid calendar month: {s!r}") from exc

    raise ValueError(f"Invalid ISO date/month format: {s!r}")


def format_answer_payload(
    ans_type: str,
    raw_answer: Any,
    fallback_to_abstain: bool = True,
) -> Tuple[str, Any]:
    """Validate and clean `(type, answer)` before writing to submission.jsonl.

    Because wrong answers incur -1 point while abstain is 0 points, any malformed
    output automatically falls back to `abstain` when `fallback_to_abstain=True`.
    """
    ans_type = str(ans_type).strip().lower()
    if ans_type not in VALID_ANSWER_TYPES:
        if fallback_to_abstain:
            return AnswerType.ABSTAIN.value, None
        raise ValueError(f"Unknown answer type: {ans_type}")

    try:
        if ans_type == AnswerType.ABSTAIN.value:
            return AnswerType.ABSTAIN.value, None

        if ans_type == AnswerType.UNANSWERABLE.value:
            return AnswerType.UNANSWERABLE.value, None

        if ans_type == AnswerType.NUMBER.value:
            return AnswerType.NUMBER.value, format_number_value(raw_answer)

        if ans_type == AnswerType.PERCENT.value:
            return AnswerType.PERCENT.value, format_percent_value(raw_answer)

        if ans_type == AnswerType.STRING.value:
            if raw_answer is None or not isinstance(raw_answer, str) or str(raw_answer).strip() == "":
                raise ValueError(f"Invalid string answer: {raw_answer!r}")
            return AnswerType.STRING.value, unicodedata.normalize("NFC", str(raw_answer).strip())

        if ans_type == AnswerType.DATE.value:
            return AnswerType.DATE.value, format_date_value(raw_answer)

        if ans_type == AnswerType.BOOLEAN.value:
            if isinstance(raw_answer, bool):
                return AnswerType.BOOLEAN.value, raw_answer
            if isinstance(raw_answer, str):
                low = raw_answer.strip().lower()
                if low in ("true", "đúng", "co", "có", "yes", "1"):
                    return AnswerType.BOOLEAN.value, True
                if low in ("false", "sai", "khong", "không", "no", "0"):
                    return AnswerType.BOOLEAN.value, False
            raise ValueError(f"Invalid boolean value: {raw_answer!r}")

        if ans_type == AnswerType.LIST.value:
            if not isinstance(raw_answer, list):
                raise ValueError("List answer must be a JSON array.")
            cleaned_list = []
            for item in raw_answer:
                if isinstance(item, (dict, list)):
                    raise ValueError(f"List items cannot be nested {type(item).__name__}.")
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    cleaned_list.append(format_number_value(item))
                elif isinstance(item, str):
                    cleaned_list.append(unicodedata.normalize("NFC", item.strip()))
                else:
                    cleaned_list.append(unicodedata.normalize("NFC", str(item).strip()))
            return AnswerType.LIST.value, cleaned_list

        if ans_type == AnswerType.TABLE.value:
            if not isinstance(raw_answer, dict):
                raise ValueError("Table answer must be a dict with 'columns' and 'rows'.")
            cols = raw_answer.get("columns")
            rows = raw_answer.get("rows")
            if not isinstance(cols, list) or not isinstance(rows, list):
                raise ValueError("Table 'columns' and 'rows' must be lists.")
            num_cols = len(cols)
            cleaned_cols = [unicodedata.normalize("NFC", str(c).strip()) for c in cols]
            cleaned_rows = []
            for r_idx, r in enumerate(rows):
                if not isinstance(r, (list, tuple)):
                    raise ValueError(f"Table row {r_idx} must be a list.")
                if len(r) != num_cols:
                    raise ValueError(
                        f"Ragged table row at {r_idx}: expected {num_cols} columns, got {len(r)}."
                    )
                cleaned_row = []
                for cell in r:
                    if isinstance(cell, (dict, list)):
                        raise ValueError(f"Table cells cannot be nested dicts/lists.")
                    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
                        cleaned_row.append(format_number_value(cell))
                    elif cell is None:
                        cleaned_row.append("")
                    else:
                        cleaned_row.append(unicodedata.normalize("NFC", str(cell).strip()))
                cleaned_rows.append(cleaned_row)
            return AnswerType.TABLE.value, {"columns": cleaned_cols, "rows": cleaned_rows}

    except Exception:
        if fallback_to_abstain:
            return AnswerType.ABSTAIN.value, None
        raise

    return AnswerType.ABSTAIN.value, None
