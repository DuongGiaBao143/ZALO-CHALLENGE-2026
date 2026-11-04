"""Deterministic Stratified Sampling of 30 Pilot Questions from train/ for Baseline Evaluation.

Rules strictly adhered to:
1. Seed = 42 for complete reproducibility.
2. Select 6 valid businesses from data/train/data/.
3. Select 5 questions per business (total 30 questions).
4. Stratify by answer `type` (number, percent, list, date, string, unanswerable, table, boolean).
5. Ground truth `answer` values are NEVER inspected or used to cherry-pick easier questions.
6. The ground truth file is saved to an isolated evaluation path (eval_gold/) outside the
   inference runner's working/result directories to prevent sandbox data leaks.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sample 30 pilot questions from train.")
    parser.add_argument(
        "--train-dir",
        type=str,
        default="data/train",
        help="Path to data/train directory.",
    )
    parser.add_argument(
        "--output-questions",
        type=str,
        default="result/baseline_7b_pilot/pilot_questions_30.jsonl",
        help="Output path for pilot questions (input only).",
    )
    parser.add_argument(
        "--output-gold",
        type=str,
        default="eval_gold/pilot_gold_30.jsonl",
        help="Output path for pilot ground truth (isolated outside sandbox reach).",
    )
    parser.add_argument(
        "--output-manifest",
        type=str,
        default="result/baseline_7b_pilot/sampling_manifest.json",
        help="Output path for sampling metadata manifest.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed = args.seed
    train_dir = Path(args.train_dir)
    q_file = train_dir / "questions.jsonl"
    a_file = train_dir / "answers.jsonl"
    biz_data_dir = train_dir / "data"

    if not q_file.exists() or not a_file.exists():
        raise FileNotFoundError(f"Missing questions.jsonl or answers.jsonl in {train_dir}")

    # Read questions and answers
    with q_file.open("r", encoding="utf-8") as f:
        questions = [json.loads(line) for line in f if line.strip()]

    with a_file.open("r", encoding="utf-8") as f:
        answers = {a["id"]: a for a in [json.loads(line) for line in f if line.strip()]}

    # Available valid businesses
    available_biz = sorted([d.name for d in biz_data_dir.iterdir() if d.is_dir()])
    if len(available_biz) < 6:
        raise ValueError(f"Found only {len(available_biz)} businesses in {biz_data_dir}, need >= 6.")

    biz_rng = random.Random(seed)
    selected_biz = sorted(biz_rng.sample(available_biz, 6))

    # Business-specific type allocation to ensure coverage of all valid answer types
    # across the 30 sampled questions (6 businesses x 5 questions)
    biz_type_plan = {
        "biz_101": {"number": 3, "date": 1, "string": 1},
        "biz_104": {"number": 1, "percent": 1, "date": 1, "list": 1, "string": 1},
        "biz_108": {"number": 2, "percent": 1, "list": 1, "date": 1},
        "biz_109": {"table": 1, "unanswerable": 1, "list": 1, "percent": 1, "number": 1},
        "biz_121": {"unanswerable": 1, "boolean": 1, "percent": 1, "number": 1, "list": 1},
        "biz_124": {"table": 1, "unanswerable": 1, "boolean": 1, "string": 1, "number": 1},
    }

    item_rng = random.Random(seed)
    selected_questions: List[Dict[str, Any]] = []
    selected_gold: List[Dict[str, Any]] = []

    for b in selected_biz:
        plan = biz_type_plan[b]
        b_qs = [q for q in questions if q["business_id"] == b]
        by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for q in sorted(b_qs, key=lambda x: x["id"]):
            t = answers[q["id"]]["type"]
            by_type[t].append(q)

        for t, count in plan.items():
            candidates = by_type[t]
            if len(candidates) < count:
                raise ValueError(
                    f"Business {b} only has {len(candidates)} questions of type '{t}', requested {count}."
                )
            sampled = item_rng.sample(candidates, count)
            for q in sampled:
                selected_questions.append(q)
                selected_gold.append(answers[q["id"]])

    # Sort final selection deterministically by question id
    paired = sorted(
        zip(selected_questions, selected_gold),
        key=lambda pair: pair[0]["id"]
    )
    final_questions = [p[0] for p in paired]
    final_gold = [p[1] for p in paired]

    assert len(final_questions) == 30
    assert len(final_gold) == 30

    # Ensure output directories exist
    out_q_path = Path(args.output_questions)
    out_q_path.parent.mkdir(parents=True, exist_ok=True)
    out_g_path = Path(args.output_gold)
    out_g_path.parent.mkdir(parents=True, exist_ok=True)
    out_m_path = Path(args.output_manifest)
    out_m_path.parent.mkdir(parents=True, exist_ok=True)

    # Write pilot questions (input only)
    with out_q_path.open("w", encoding="utf-8") as f:
        for q in final_questions:
            # Only keep input fields: id, business_id, question, as_of_date
            clean_q = {
                "id": q["id"],
                "business_id": q["business_id"],
                "question": q["question"],
                "as_of_date": q["as_of_date"],
            }
            f.write(json.dumps(clean_q, ensure_ascii=False) + "\n")

    # Write gold ground truth (isolated)
    with out_g_path.open("w", encoding="utf-8") as f:
        for g in final_gold:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")

    # Generate summary manifest
    type_counts = dict(Counter(g["type"] for g in final_gold))
    biz_counts = dict(Counter(q["business_id"] for q in final_questions))

    manifest = {
        "seed": seed,
        "total_questions": len(final_questions),
        "selected_businesses": selected_biz,
        "questions_per_business": biz_counts,
        "type_distribution": type_counts,
        "questions_file": str(out_q_path),
        "isolated_gold_file": str(out_g_path),
        "items": [
            {
                "id": q["id"],
                "business_id": q["business_id"],
                "as_of_date": q["as_of_date"],
                "type": answers[q["id"]]["type"],
                "question": q["question"],
            }
            for q in final_questions
        ],
    }

    with out_m_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"Successfully selected {len(final_questions)} pilot questions:")
    print(f"  - Questions: {out_q_path}")
    print(f"  - Isolated Gold: {out_g_path}")
    print(f"  - Manifest: {out_m_path}")
    print(f"  - Type distribution: {type_counts}")
    print(f"  - Businesses: {selected_biz}")


if __name__ == "__main__":
    main()
