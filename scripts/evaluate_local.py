#!/usr/bin/env python3
"""CLI tool to evaluate a local `submission.jsonl` against a reference ground-truth `.jsonl`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.eval.scorer import evaluate_predictions


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute official Penalized Accuracy (PA) on local predictions."
    )
    parser.add_argument(
        "--pred",
        type=Path,
        required=True,
        help="Path to predicted submission.jsonl",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        required=True,
        help="Path to reference ground-truth answers.jsonl",
    )
    args = parser.parse_args()

    preds = _load_jsonl(args.pred)
    golds = _load_jsonl(args.gold)

    report = evaluate_predictions(predictions=preds, references=golds)
    print(report.format_summary())


if __name__ == "__main__":
    main()
