"""Bộ câu hỏi cố định để so sánh mọi lần chạy. Đáp án chỉ dùng để chấm, không đưa cho solver."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8-sig").splitlines() if l.strip()]


@dataclass
class EvalSet:
    name: str
    split_dir: Path            # thư mục có questions.jsonl, rulebook.md, calendar.csv, data/<business_id>/
    items: list[dict]          # {id, business_id, question, as_of_date}
    gold: dict[str, dict] = field(repr=False)   # id -> {id, type, answer, alias}

    def __len__(self) -> int:
        return len(self.items)


def _build(name: str, split_dir: Path, gold_rows: list[dict]) -> EvalSet:
    gold = {g["id"]: g for g in gold_rows}
    questions = {q["id"]: q for q in load_jsonl(split_dir / "questions.jsonl")}
    missing = sorted(set(gold) - set(questions))
    assert not missing, f"{name}: {len(missing)} câu có đáp án nhưng không có trong questions.jsonl"
    return EvalSet(name, split_dir, [questions[i] for i in sorted(gold)], gold)


def unseen_50() -> EvalSet:
    """50 câu cùng phân phối với train (shop bán hàng), không nằm trong tập sinh mẫu RFT."""
    return _build("unseen_50", ROOT / "data" / "train", load_jsonl(ROOT / "eval_gold" / "unseen_gold_50.jsonl"))


def private_50(n: int = 50, seed: int = 0) -> EvalSet:
    """n câu có đáp án của private_test (rulebook và loại hình shop khác train), chọn ngẫu nhiên có seed."""
    split = ROOT / "data" / "private_test" / "private_test"
    rows = sorted(load_jsonl(split / "answer.jsonl"), key=lambda r: r["id"])
    rows = sorted(random.Random(seed).sample(rows, n), key=lambda r: r["id"])
    return _build(f"private_{n}", split, rows)


SETS = {"unseen_50": unseen_50, "private_50": private_50}


def get(name: str) -> EvalSet:
    if name not in SETS:
        raise SystemExit(f"bộ câu không có: {name}; chọn trong {sorted(SETS)}")
    return SETS[name]()
