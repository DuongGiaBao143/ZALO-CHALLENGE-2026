"""Script to standardize and assemble a clean SFT dataset for Qwen2.5-Coder.

Takes compact id/business_id/code records (or legacy verified traces),
regenerates clean system and user prompts from the local training split
using the current repository pipeline (folder, README, schema and question/date),
and outputs a ready-to-train single-turn SFT dataset in ChatML format.

Strictly follows AGENTS.md: reads data/ in read-only mode, outputs to result/.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict

# Ensure project root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from src.agent.sandbox import extract_python_code
from src.agent.solver import resolve_business_path
from src.coder_training.io_utils import read_unique_jsonl, writable_output
from src.profiler.business_loader import format_profile_for_prompt, profile_business_package
from src.schemas import QuestionItem
from src.time_resolver.calendar_utils import load_shared_context, resolve_relative_dates

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def build_sft_records(
    input_jsonl_path: str,
    data_train_dir: str = "data/train",
) -> list[dict]:
    """Build machine-independent prompts from IDs/code and the local train split."""
    input_path = Path(input_jsonl_path)
    train_dir = Path(data_train_dir)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # 1. Load questions lookup
    questions_file = train_dir / "questions.jsonl"
    logger.info("Loading questions from %s", questions_file)
    questions: Dict[str, dict] = {}
    with open(questions_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                questions[item["id"]] = item

    # 2. Load shared context (calendar_path, rulebook_text)
    logger.info("Loading shared context from %s", train_dir)
    shared_ctx = load_shared_context(str(train_dir))
    calendar_path = shared_ctx.get("calendar_path", "")
    rulebook_text = shared_ctx.get("rulebook_text", "")

    # 3. Cache business profiles to avoid re-computing schemas
    profile_cache: Dict[str, str] = {}

    def get_schema_markdown(biz_id: str) -> str:
        if biz_id in profile_cache:
            return profile_cache[biz_id]
        biz_dir = resolve_business_path(train_dir, biz_id)
        logger.info("Profiling business package: %s at %s", biz_id, biz_dir)
        profile = profile_business_package(business_dir=str(biz_dir), business_id=biz_id,
                                           max_sample_rows=0, max_unique_categorical=0)
        if profile.error:
            raise ValueError(f"Cannot profile {biz_id}: {profile.error}")
        schema_md = format_profile_for_prompt(profile, compact=True)
        profile_cache[biz_id] = schema_md
        return schema_md

    # 4. Read input records and build clean SFT items
    logger.info("Processing raw verified dataset from %s", input_path)
    clean_records = []
    skipped = 0

    for line_num, raw in enumerate(read_unique_jsonl(input_path), start=1):
        qid = raw.get("id")
        if not qid or qid not in questions:
            if "code" in raw:
                raise ValueError(f"Question ID {qid!r} not found in {questions_file}")
            logger.warning("Line %d: Question ID '%s' not found in questions.jsonl, skipping", line_num, qid)
            skipped += 1
            continue

        q_item = questions[qid]
        QuestionItem.from_dict(q_item)
        biz_id = q_item["business_id"]
        if raw.get("business_id") != biz_id:
            raise ValueError(f"business_id mismatch for {qid}: expected {biz_id}")
        question = q_item["question"]
        as_of_date = q_item["as_of_date"]

        # Extract final verified python code from last assistant turn
        if "code" in raw:
            code = raw["code"]
            if not isinstance(code, str) or not code.strip():
                raise ValueError(f"Missing Python code for {qid}")
            compile(code, f"<SFT {qid}>", "exec")
        else:
            assistant_msgs = [m for m in raw.get("messages", []) if m.get("role") == "assistant"]
            code = extract_python_code(assistant_msgs[-1].get("content", "")) if assistant_msgs else None
        if not code:
            logger.warning("Line %d: Failed to extract Python code for %s, skipping", line_num, qid)
            skipped += 1
            continue

        # Standardized code block
        formatted_code = f"```python\n{code}\n```"

        # Build standardized user prompt matching current solver pipeline
        rel_dates = resolve_relative_dates(as_of_date)
        schema_md = get_schema_markdown(biz_id)
        user_prompt = build_user_prompt(
            question=question,
            as_of_date=as_of_date,
            relative_dates=rel_dates,
            schema_markdown=schema_md,
            rulebook_text=rulebook_text,
            calendar_path=calendar_path,
        )

        clean_item = {
            "id": qid,
            "business_id": biz_id,
            "prompt_format": "folder_readme_schema_v1",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": formatted_code},
            ],
        }
        clean_records.append(clean_item)

    if not clean_records:
        raise ValueError("No SFT records could be prepared")
    logger.info("Prepared %d records (skipped: %d)", len(clean_records), skipped)
    return clean_records


def build_sft_dataset(
    input_jsonl_path: str,
    data_train_dir: str = "data/train",
    output_jsonl_path: str = "result/sft_train_ready.jsonl",
) -> None:
    output_path = writable_output(output_jsonl_path, data_train_dir, input_jsonl_path)
    clean_records = build_sft_records(input_jsonl_path, data_train_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 5. Write to output file
    logger.info("Writing %d clean SFT records to %s", len(clean_records), output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        for rec in clean_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 6. Report metrics
    u_lens = [len(r["messages"][1]["content"]) for r in clean_records]
    a_lens = [len(r["messages"][2]["content"]) for r in clean_records]
    logger.info("=== SFT DATASET BUILD COMPLETE ===")
    logger.info("Total clean records: %d", len(clean_records))
    logger.info("User prompt char length: min=%d, max=%d, avg=%.0f (~%.0f tokens)",
                min(u_lens), max(u_lens), sum(u_lens)/len(u_lens), (sum(u_lens)/len(u_lens))/3.2)
    logger.info("Assistant code char length: min=%d, max=%d, avg=%.0f (~%.0f tokens)",
                min(a_lens), max(a_lens), sum(a_lens)/len(a_lens), (sum(a_lens)/len(a_lens))/3.5)
    logger.info("Input format: folder + README + columns/dtypes + question/as_of_date; rulebook via runtime path")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Assemble standardized SFT dataset")
    parser.add_argument(
        "--input",
        type=str,
        default="verified_sft_dataset.jsonl",
        help="Path to IDs/code JSONL or legacy verified messages",
    )
    parser.add_argument(
        "--data_dir",
        type=str,
        default="data/train",
        help="Path to training data directory containing questions.jsonl and data/ folders",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="result/sft_train_ready.jsonl",
        help="Path to output cleaned SFT dataset",
    )
    args = parser.parse_args()
    build_sft_dataset(args.input, args.data_dir, args.output)
