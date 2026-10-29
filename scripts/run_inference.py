#!/usr/bin/env python3
"""Main inference entrypoint for Zalo AI Challenge 2026 — DataMate.

Reads `/data/questions.jsonl`, runs DataMateAgent, streams each prediction line-by-line
to `/result/submission.jsonl` (flushing immediately), and writes per-question logs to
`/result/logs/<question_id>.json` as required by the Data & Submission Format specification.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import yaml
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.solver import DataMateAgent
from src.schemas import QuestionItem, SubmissionItem


def setup_logging(log_file: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run DataMate inference pipeline.")
    parser.add_argument(
        "--config",
        type=str,
        default="configs/default_config.yaml",
        help="Path to YAML configuration file.",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Override data directory (default: /data, or data/train, data/public_test).",
    )
    parser.add_argument(
        "--questions-file",
        type=str,
        default=None,
        help="Optional explicit path to questions.jsonl (default: <data-dir>/questions.jsonl).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Override output submission.jsonl path (default: /result/submission.jsonl).",
    )
    parser.add_argument(
        "--logs-dir",
        type=str,
        default=None,
        help="Directory for per-question logs (default: <output_dir>/logs).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on number of questions to run (for quick local testing).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline in dry_run mode (no GPU / vLLM required) to test I/O and formatting.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg_path = Path(args.config)
    with cfg_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    if args.dry_run:
        config.setdefault("model", {})["backend"] = "dry_run"

    paths_cfg = config.get("paths", {})
    data_dir = Path(args.data_dir or paths_cfg.get("data_dir", "/data"))
    output_path = Path(args.output or paths_cfg.get("output_file", "/result/submission.jsonl"))
    logs_dir = Path(args.logs_dir) if args.logs_dir else (output_path.parent / "logs")
    log_file = paths_cfg.get("log_file", str(output_path.parent / "run.log"))

    setup_logging(log_file)
    logger = logging.getLogger("run_inference")

    questions_path = (
        Path(args.questions_file)
        if args.questions_file
        else data_dir / "questions.jsonl"
    )
    if not questions_path.exists():
        logger.error("Questions file not found: %s", questions_path)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    questions: list[QuestionItem] = []
    with questions_path.open("r", encoding="utf-8") as qf:
        for line_no, line in enumerate(qf, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                questions.append(QuestionItem.from_dict(json.loads(line)))
            except Exception as exc:
                logger.error("Invalid JSON on line %d of %s: %s", line_no, questions_path, exc)
                raise

    if args.limit is not None and args.limit > 0:
        questions = questions[: args.limit]

    logger.info("Loaded %d questions from %s", len(questions), questions_path)
    start_time = time.time()

    agent = DataMateAgent(config=config, data_dir=data_dir)

    with output_path.open("w", encoding="utf-8") as out_f:
        for q_item in tqdm(questions, desc="Solving questions"):
            q_t0 = time.time()
            try:
                sub_item, trace = agent.answer_question_with_trace(q_item)
            except Exception as exc:
                logger.exception(
                    "Unhandled error on question %s, falling back to abstain: %s",
                    q_item.id,
                    exc,
                )
                sub_item = SubmissionItem.abstain(q_item.id)
                trace = {
                    "id": q_item.id,
                    "business_id": q_item.business_id,
                    "question": q_item.question,
                    "final_answer": sub_item.to_dict(),
                    "elapsed_time_sec": round(time.time() - q_t0, 4),
                    "error": str(exc),
                }

            out_f.write(json.dumps(sub_item.to_dict(), ensure_ascii=False) + "\n")
            out_f.flush()

            # Write per-question log to /result/logs/<id>.json (Rule 8 & data.md requirement)
            q_log_file = logs_dir / f"{q_item.id}.json"
            with q_log_file.open("w", encoding="utf-8") as lf:
                json.dump(trace, lf, ensure_ascii=False, indent=2)

            logger.info(
                "Question %s (%s) -> type=%s in %.2fs",
                q_item.id,
                q_item.business_id,
                sub_item.type,
                trace.get("elapsed_time_sec", time.time() - q_t0),
            )

    elapsed = time.time() - start_time
    logger.info(
        "Completed %d questions in %.2fs. Output saved to %s (per-question logs in %s)",
        len(questions),
        elapsed,
        output_path,
        logs_dir,
    )


if __name__ == "__main__":
    main()
