"""Data models and type definitions for Zalo AI Challenge 2026 — DataMate."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class AnswerType(str, Enum):
    """Allowed output types defined in the Evaluation specification."""

    NUMBER = "number"
    PERCENT = "percent"
    STRING = "string"
    DATE = "date"
    BOOLEAN = "boolean"
    LIST = "list"
    TABLE = "table"
    UNANSWERABLE = "unanswerable"
    ABSTAIN = "abstain"


VALID_ANSWER_TYPES = {t.value for t in AnswerType}


class ProtocolKind(str, Enum):
    """Protocol message kinds emitted by agent-generated scripts."""

    OBSERVATION = "observation"
    FINAL = "final"
    ERROR = "error"


@dataclass
class QuestionItem:
    """Represents one line of questions.jsonl."""

    id: str
    business_id: str
    question: str
    as_of_date: str

    def validate(self) -> None:
        """Validate question fields to reject invalid metadata, non-dates, or directory traversal."""
        if not self.id or not str(self.id).strip():
            raise ValueError("Question id cannot be empty.")
        qid = str(self.id).strip()
        if not re.match(r"^[A-Za-z0-9_\-]+$", qid):
            raise ValueError(f"Invalid characters in question id (potential path traversal): {qid!r}")

        if not self.business_id or not str(self.business_id).strip():
            raise ValueError("business_id cannot be empty.")
        bid = str(self.business_id).strip()
        if not re.match(r"^[A-Za-z0-9_\-]+$", bid):
            raise ValueError(f"Invalid characters in business_id (potential path traversal): {bid!r}")

        if not self.question or not str(self.question).strip():
            raise ValueError("Question text cannot be empty.")

        if not self.as_of_date or not str(self.as_of_date).strip():
            raise ValueError("as_of_date cannot be empty.")
        # Validate that as_of_date is an actual, valid calendar date (YYYY-MM-DD)
        try:
            parsed_date = datetime.strptime(str(self.as_of_date).strip(), "%Y-%m-%d")
            # Reformat to ensure exact YYYY-MM-DD match without extra trailing garbage
            if parsed_date.strftime("%Y-%m-%d") != str(self.as_of_date).strip():
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"as_of_date must be a valid calendar date in YYYY-MM-DD format, got: {self.as_of_date!r}"
            ) from exc

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuestionItem":
        item = cls(
            id=str(data["id"]),
            business_id=str(data["business_id"]),
            question=str(data["question"]),
            as_of_date=str(data["as_of_date"]),
        )
        item.validate()
        return item


@dataclass
class SubmissionItem:
    """Represents one line of submission.jsonl adhering to the official contract (id, type, answer)."""

    id: str
    type: str
    answer: Any = None
    evidence: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to official submission JSON format: {id, type, answer}.

        For unanswerable and abstain types, answer is always None.
        """
        if self.type in (AnswerType.UNANSWERABLE.value, AnswerType.ABSTAIN.value):
            payload = {"id": self.id, "type": self.type, "answer": None}
        else:
            payload = {"id": self.id, "type": self.type, "answer": self.answer}
        return payload

    @classmethod
    def abstain(cls, question_id: str, reason: Optional[str] = None) -> "SubmissionItem":
        return cls(id=question_id, type=AnswerType.ABSTAIN.value, answer=None, reason=reason)

    @classmethod
    def unanswerable(
        cls, question_id: str, reason: Optional[str] = None, evidence: Optional[str] = None
    ) -> "SubmissionItem":
        return cls(
            id=question_id,
            type=AnswerType.UNANSWERABLE.value,
            answer=None,
            evidence=evidence,
            reason=reason,
        )


@dataclass
class TableSchema:
    """Extracted metadata for a single table/sheet inside a business package."""

    source_file: str
    table_name: str
    columns: List[str]
    dtypes: Dict[str, str]
    row_count: Optional[int]
    sample_rows: List[Dict[str, Any]] = field(default_factory=list)
    categorical_values: Dict[str, List[str]] = field(default_factory=dict)
    status: str = "ok"  # "ok", "partial", "error"
    date_range: Optional[Dict[str, str]] = None
    candidate_header_row: Optional[int] = 0
    header_uncertainty: bool = False
    raw_preview: List[List[Any]] = field(default_factory=list)
    truncated_rows: bool = False
    truncated_categorical: bool = False
    error_message: Optional[str] = None
    column_unique_counts: Dict[str, int] = field(default_factory=dict)
    exhaustive_columns: List[str] = field(default_factory=list)


@dataclass
class BusinessProfile:
    """Complete profile of a business data package."""

    business_id: str
    business_dir: str
    readme_text: str
    tables: List[TableSchema] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    file_inventory: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
