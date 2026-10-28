"""Data models and type definitions for Zalo AI Challenge 2026 — DataMate."""

from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass
class QuestionItem:
    """Represents one line of questions.jsonl."""

    id: str
    business_id: str
    question: str
    as_of_date: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuestionItem":
        return cls(
            id=str(data["id"]),
            business_id=str(data["business_id"]),
            question=str(data["question"]),
            as_of_date=str(data["as_of_date"]),
        )


@dataclass
class SubmissionItem:
    """Represents one line of submission.jsonl."""

    id: str
    type: str
    answer: Any = None

    def to_dict(self) -> Dict[str, Any]:
        if self.type in (AnswerType.UNANSWERABLE.value, AnswerType.ABSTAIN.value):
            return {"id": self.id, "type": self.type, "answer": None}
        return {"id": self.id, "type": self.type, "answer": self.answer}

    @classmethod
    def abstain(cls, question_id: str) -> "SubmissionItem":
        return cls(id=question_id, type=AnswerType.ABSTAIN.value, answer=None)

    @classmethod
    def unanswerable(cls, question_id: str) -> "SubmissionItem":
        return cls(id=question_id, type=AnswerType.UNANSWERABLE.value, answer=None)


@dataclass
class TableSchema:
    """Extracted metadata for a single table/sheet inside a business package."""

    source_file: str
    table_name: str
    columns: List[str]
    dtypes: Dict[str, str]
    row_count: int
    sample_rows: List[Dict[str, Any]] = field(default_factory=list)
    categorical_values: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class BusinessProfile:
    """Complete profile of a business data package."""

    business_id: str
    business_dir: str
    readme_text: str
    tables: List[TableSchema] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    error: Optional[str] = None
