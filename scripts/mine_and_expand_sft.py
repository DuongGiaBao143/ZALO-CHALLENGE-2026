#!/usr/bin/env python3
"""Zalo AI Challenge 2026 — DataMate
SFT Dataset Expansion via Rejection Sampling / Expert Iteration (STaR).

Features:
1. Mine existing inference logs (e.g. from pilot runs or previous benchmarks).
2. Generate new candidate trajectories for unseen training questions using Qwen 7B.
3. Multi-gate strict screening:
   - Gate 1: Execution success in sandbox (exit code 0, no exception, valid JSON output).
   - Gate 2: Official Penalized Accuracy (+1.0 pt against ground-truth answers.jsonl).
   - Gate 3: AST & Security Verification (`is_safe_code`):
     * Anti-leak: no access to forbidden files (answers.jsonl, test splits).
     * Anti-hardcoded question IDs or cheat patterns.
     * AST check: genuine data access (calls read_csv, read_excel, sqlite3, open, etc.).
   - Gate 4: Deduplication: only adds new, unseen questions to `sft_train_ready.jsonl`.
4. Outputs standardized single-turn ChatML format with Recency Anchor.
5. Automatically syncs updated dataset to Google Drive when available.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from src.agent.sandbox import SandboxResult, extract_python_code, run_python_in_sandbox
from src.coder_training.collector import is_safe_code
from src.eval.scorer import score_single_answer
from src.profiler.business_loader import format_profile_for_prompt, profile_business_package
from src.time_resolver.calendar_utils import load_shared_context, resolve_relative_dates

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def sanitize_code(code: str) -> str:
    """Strip any hardcoded environment path assignments copied from prompts."""
    cleaned = re.sub(r'^\s*(BUSINESS_DIR|CALENDAR_PATH)\s*=\s*["\'/].*$\n?', '', code, flags=re.MULTILINE)
    return cleaned.strip()


def verify_code_solution(
    code: str,
    question_id: str,
    biz_dir: Path,
    as_of_date: str,
    calendar_path: str,
    rulebook_path: str,
    gold_answer: Dict[str, Any],
    timeout_sec: int = 35,
) -> Tuple[bool, str, Optional[Dict[str, Any]], Optional[SandboxResult]]:
    """Run code in sandbox and verify against gold answer and safety filters."""
    # 1. Basic length & shortcut check
    clean_code = sanitize_code(code)
    if not clean_code or len(clean_code.strip()) < 30:
        return False, "Code too short or empty", None, None

    # 2. Safety & AST data-access check
    safe, reason = is_safe_code(clean_code, question_id)
    if not safe:
        return False, f"Safety check failed: {reason}", None, None

    # 3. Sandbox execution
    try:
        sandbox_res = run_python_in_sandbox(
            code=clean_code,
            business_dir=str(biz_dir),
            calendar_path=calendar_path,
            as_of_date=as_of_date,
            rulebook_path=rulebook_path,
            timeout_sec=timeout_sec,
        )
    except Exception as exc:
        return False, f"Sandbox execution exception: {exc}", None, None

    if not sandbox_res.success:
        return False, f"Execution failed: {sandbox_res.error_message}", None, sandbox_res

    # 4. Check JSON protocol output
    pred_payload = sandbox_res.parsed_output
    if not pred_payload or sandbox_res.kind != "final":
        return False, f"Invalid protocol output (kind={sandbox_res.kind})", None, sandbox_res

    # 5. Score against gold answer
    verdict, score = score_single_answer(pred_payload, gold_answer)
    if verdict != "correct" or score != 1.0:
        return False, f"Answer mismatch (verdict={verdict}, score={score})", pred_payload, sandbox_res

    return True, "PASSED_ALL_GATES", pred_payload, sandbox_res


def mine_logs_directory(
    logs_dir: Path,
    gold_answers: Dict[str, Dict[str, Any]],
    questions: Dict[str, Dict[str, Any]],
    data_dir: Path,
    calendar_path: str,
    rulebook_path: str,
    existing_ids: Set[str],
) -> List[Dict[str, Any]]:
    """Scan an existing logs directory for verified correct code solutions."""
    logger.info("Scanning logs in %s ...", logs_dir)
    accepted_samples = []

    log_files = sorted(logs_dir.glob("*.json"))
    logger.info("Found %d log files to inspect.", len(log_files))

    for log_path in log_files:
        qid = log_path.stem
        if qid in existing_ids:
            continue
        if qid not in gold_answers or qid not in questions:
            continue

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                log_data = json.load(f)
        except Exception as exc:
            logger.warning("Could not parse log %s: %exc", log_path, exc)
            continue

        q_item = questions[qid]
        g_item = gold_answers[qid]
        biz_id = q_item["business_id"]
        biz_dir = data_dir / "data" / biz_id
        if not biz_dir.exists():
            biz_dir = data_dir / biz_id

        # Find best code attempt
        attempts = log_data.get("attempts", [])
        if not attempts:
            continue

        # Look at the final attempt or find any successful final attempt
        candidate_code = None
        for att in reversed(attempts):
            if att.get("generated_code") and att.get("kind") == "final":
                candidate_code = att["generated_code"]
                break

        if not candidate_code:
            continue

        passed, reason, pred_payload, _ = verify_code_solution(
            code=candidate_code,
            question_id=qid,
            biz_dir=biz_dir,
            as_of_date=q_item["as_of_date"],
            calendar_path=calendar_path,
            rulebook_path=rulebook_path,
            gold_answer=g_item,
        )

        if passed:
            logger.info("✅ ACCEPTED from logs: [%s] (%s) - Ans: %r", qid, biz_id, g_item.get("answer"))
            accepted_samples.append({
                "id": qid,
                "business_id": biz_id,
                "clean_code": sanitize_code(candidate_code),
            })
        else:
            logger.debug("Rejected [%s]: %s", qid, reason)

    logger.info("Log mining complete: %d new verified samples accepted.", len(accepted_samples))
    return accepted_samples


def format_sft_record(
    qid: str,
    biz_id: str,
    code: str,
    questions: Dict[str, Dict[str, Any]],
    data_dir: Path,
    calendar_path: str,
    rulebook_text: str,
    profile_cache: Dict[str, str],
) -> Dict[str, Any]:
    """Build standardized ChatML single-turn record with Recency Anchor."""
    q_item = questions[qid]
    question = q_item["question"]
    as_of_date = q_item["as_of_date"]

    if biz_id not in profile_cache:
        biz_dir = data_dir / "data" / biz_id
        if not biz_dir.exists():
            biz_dir = data_dir / biz_id
        prof = profile_business_package(str(biz_dir), business_id=biz_id)
        profile_cache[biz_id] = format_profile_for_prompt(prof, compact=True)

    schema_md = profile_cache[biz_id]
    rel_dates = resolve_relative_dates(as_of_date)

    user_prompt = build_user_prompt(
        question=question,
        as_of_date=as_of_date,
        relative_dates=rel_dates,
        schema_markdown=schema_md,
        rulebook_text=rulebook_text,
        calendar_path=calendar_path,
    )

    clean_code = sanitize_code(code)
    formatted_code = f"```python\n{clean_code}\n```"

    return {
        "id": qid,
        "business_id": biz_id,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": formatted_code},
        ],
    }


def run_rollout_vllm(
    model_id: str,
    target_questions: List[Dict[str, Any]],
    gold_answers: Dict[str, Dict[str, Any]],
    train_dir: Path,
    calendar_path: str,
    rulebook_path: str,
    rulebook_text: str,
    profile_cache: Dict[str, str],
    batch_size: int = 16,
    max_tokens: int = 768,
    max_model_len: int = 16384,
    gpu_util: float = 0.85,
    sandbox_timeout: int = 35,
    lora_adapter: Optional[str] = None,
    tensor_parallel_size: int = 1,
    dtype: str = "auto",
) -> List[Dict[str, Any]]:
    """Generate solution candidates using vLLM in parallel batches and sieve with sandbox + gold."""
    try:
        from vllm import LLM, SamplingParams
        from vllm.lora.request import LoRARequest
        from transformers import AutoTokenizer
    except ImportError as e:
        logger.error("vllm is required for --rollout-vllm. Run: pip install vllm (%s)", e)
        return []

    lora_path = None
    if lora_adapter:
        candidate_lora = Path(lora_adapter).resolve()
        if (candidate_lora / "final_adapter" / "adapter_config.json").exists():
            lora_path = candidate_lora / "final_adapter"
        elif (candidate_lora / "adapter_config.json").exists():
            lora_path = candidate_lora
        elif candidate_lora.exists():
            lora_path = candidate_lora
        else:
            raise FileNotFoundError(f"Không tìm thấy adapter LoRA tại: {candidate_lora}")
        logger.info("🎯 Loading LoRA Adapter: %s", lora_path)

    logger.info("Initializing vLLM Engine (%s) with gpu_util=%.2f, tp=%d, dtype=%s, lora=%s...",
                model_id, gpu_util, tensor_parallel_size, dtype, bool(lora_path))
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    llm = LLM(
        model=model_id,
        tensor_parallel_size=tensor_parallel_size,
        gpu_memory_utilization=gpu_util,
        max_model_len=max_model_len,
        trust_remote_code=True,
        dtype=dtype,
        seed=42,
        enable_lora=bool(lora_path),
        max_lora_rank=64 if lora_path else 16,
    )
    sampling_params = SamplingParams(
        temperature=0.0,
        max_tokens=max_tokens,
    )

    accepted_samples = []
    logger.info("Starting vLLM rollout for %d target questions (batch_size=%d)...",
                len(target_questions), batch_size)

    for i in range(0, len(target_questions), batch_size):
        batch_q = target_questions[i:i + batch_size]
        prompts = []
        metadata = []

        for q_item in batch_q:
            qid = q_item["id"]
            biz_id = q_item["business_id"]
            if qid not in gold_answers:
                continue

            if biz_id not in profile_cache:
                biz_dir = train_dir / "data" / biz_id
                if not biz_dir.exists():
                    biz_dir = train_dir / biz_id
                prof = profile_business_package(str(biz_dir), business_id=biz_id)
                profile_cache[biz_id] = format_profile_for_prompt(prof, compact=True)

            schema_md = profile_cache[biz_id]
            rel_dates = resolve_relative_dates(q_item["as_of_date"])
            user_prompt = build_user_prompt(
                question=q_item["question"],
                as_of_date=q_item["as_of_date"],
                relative_dates=rel_dates,
                schema_markdown=schema_md,
                rulebook_text=rulebook_text,
                calendar_path=calendar_path,
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            prompts.append(prompt)
            metadata.append(q_item)

        if not prompts:
            continue

        lora_req = LoRARequest("datamate_sft_lora", 1, str(lora_path)) if lora_path else None
        outputs = llm.generate(prompts, sampling_params, lora_request=lora_req, use_tqdm=False)

        for q_item, output in zip(metadata, outputs):
            qid = q_item["id"]
            biz_id = q_item["business_id"]
            g_item = gold_answers[qid]
            biz_dir = train_dir / "data" / biz_id
            if not biz_dir.exists():
                biz_dir = train_dir / biz_id

            completion_text = output.outputs[0].text if output.outputs else ""
            code = extract_python_code(completion_text)
            if not code:
                continue

            passed, reason, pred_payload, _ = verify_code_solution(
                code=code,
                question_id=qid,
                biz_dir=biz_dir,
                as_of_date=q_item["as_of_date"],
                calendar_path=calendar_path,
                rulebook_path=rulebook_path,
                gold_answer=g_item,
                timeout_sec=sandbox_timeout,
            )

            if passed:
                logger.info("🎯 [vLLM HIT] Accepted [%s] (%s) - Ans: %r", qid, biz_id, g_item.get("answer"))
                accepted_samples.append({
                    "id": qid,
                    "business_id": biz_id,
                    "clean_code": sanitize_code(code),
                })
            else:
                logger.debug("Rejected [%s]: %s", qid, reason)

    logger.info("vLLM rollout finished: %d newly verified samples accepted.", len(accepted_samples))
    return accepted_samples


def main():
    parser = argparse.ArgumentParser(description="Mine and expand verified SFT dataset for DataMate")
    parser.add_argument("--sft-dataset", type=str, default="result/sft_train_ready.jsonl",
                        help="Path to current sft_train_ready.jsonl")
    parser.add_argument("--data-train", type=str, default="data/train",
                        help="Path to data/train directory")
    parser.add_argument("--scan-logs", type=str, nargs="*", default=[],
                        help="List of log directories to scan for correct code (e.g. result/sft_7b_pilot/logs)")
    parser.add_argument("--rollout-vllm", action="store_true",
                        help="Run high-throughput vLLM rollout on unseen training questions")
    parser.add_argument("--model", type=str, default="Qwen/Qwen2.5-Coder-7B-Instruct",
                        help="Model ID or path for rollout generation")
    parser.add_argument("--limit", type=int, default=100,
                        help="Max number of unseen questions to attempt in rollout")
    parser.add_argument("--batch-size", type=int, default=16,
                        help="Batch size for vLLM rollout")
    parser.add_argument("--lora-adapter", type=str, default=None,
                        help="Path to trained LoRA adapter (e.g. result/sft_adapter_qwen7b/final_adapter)")
    parser.add_argument("--tensor-parallel-size", "--tp", type=int, default=1,
                        help="Tensor parallel size (e.g. 2 for Kaggle T4x2)")
    parser.add_argument("--dtype", default="auto", choices=["auto", "bfloat16", "float16"],
                        help="Data type for vLLM (use float16 on T4, bfloat16 on A100)")
    parser.add_argument("--gdrive-dir", type=str,
                        default="/content/drive/MyDrive/Colab Notebooks/ZALO-AI-CHALLENGE-2026/result",
                        help="Optional Google Drive destination directory for auto-sync")
    parser.add_argument("--output", type=str, default=None,
                        help="Optional output path (defaults to overwriting/updating --sft-dataset)")
    args = parser.parse_args()

    sft_path = Path(args.sft_dataset)
    train_dir = Path(args.data_train)
    output_path = Path(args.output) if args.output else sft_path

    # 1. Load existing SFT dataset
    existing_records = []
    existing_ids = set()
    if sft_path.exists():
        with open(sft_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    existing_records.append(rec)
                    if "id" in rec:
                        existing_ids.add(rec["id"])
    logger.info("Current SFT dataset has %d verified samples.", len(existing_records))

    # 2. Load questions and gold answers
    questions_file = train_dir / "questions.jsonl"
    answers_file = train_dir / "answers.jsonl"
    calendar_file = train_dir / "calendar.csv"
    rulebook_file = train_dir / "rulebook.md"

    logger.info("Loading training questions from %s ...", questions_file)
    with open(questions_file, "r", encoding="utf-8") as f:
        questions = {item["id"]: item for item in (json.loads(line) for line in f if line.strip())}

    logger.info("Loading ground-truth answers from %s ...", answers_file)
    with open(answers_file, "r", encoding="utf-8") as f:
        gold_answers = {item["id"]: item for item in (json.loads(line) for line in f if line.strip())}

    shared_ctx = load_shared_context(str(train_dir))
    calendar_path = shared_ctx.get("calendar_path", str(calendar_file))
    rulebook_text = shared_ctx.get("rulebook_text", "")
    if not rulebook_text and rulebook_file.exists():
        rulebook_text = rulebook_file.read_text(encoding="utf-8")

    profile_cache = {}
    newly_accepted = []

    # 3. Mine from log directories
    for log_dir_str in args.scan_logs:
        log_dir = Path(log_dir_str)
        if log_dir.exists():
            mined = mine_logs_directory(
                logs_dir=log_dir,
                gold_answers=gold_answers,
                questions=questions,
                data_dir=train_dir,
                calendar_path=calendar_path,
                rulebook_path=str(rulebook_file),
                existing_ids=existing_ids,
            )
            for item in mined:
                if item["id"] not in existing_ids:
                    existing_ids.add(item["id"])
                    newly_accepted.append(item)
        else:
            logger.warning("Log directory %s does not exist, skipping.", log_dir)

    # 3b. Run vLLM rollout on unseen training questions if requested
    if args.rollout_vllm:
        unseen_q = [q for q in questions.values() if q["id"] not in existing_ids]
        target_q = unseen_q[:args.limit]
        logger.info("Selected %d unseen questions for vLLM rollout (out of %d remaining)",
                    len(target_q), len(unseen_q))
        mined_vllm = run_rollout_vllm(
            model_id=args.model,
            target_questions=target_q,
            gold_answers=gold_answers,
            train_dir=train_dir,
            calendar_path=calendar_path,
            rulebook_path=str(rulebook_file),
            rulebook_text=rulebook_text,
            profile_cache=profile_cache,
            batch_size=args.batch_size,
            lora_adapter=args.lora_adapter,
            tensor_parallel_size=args.tensor_parallel_size,
            dtype=args.dtype,
        )
        for item in mined_vllm:
            if item["id"] not in existing_ids:
                existing_ids.add(item["id"])
                newly_accepted.append(item)

    # 4. Format and append newly accepted samples
    if newly_accepted:
        logger.info("Formatting %d newly accepted samples into ChatML format...", len(newly_accepted))
        for item in newly_accepted:
            sft_rec = format_sft_record(
                qid=item["id"],
                biz_id=item["business_id"],
                code=item["clean_code"],
                questions=questions,
                data_dir=train_dir,
                calendar_path=calendar_path,
                rulebook_text=rulebook_text,
                profile_cache=profile_cache,
            )
            existing_records.append(sft_rec)

        # Write updated dataset
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for rec in existing_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        logger.info("🎉 Dataset successfully expanded! Total samples: %d (+%d new)",
                    len(existing_records), len(newly_accepted))

        # Sync to Google Drive if available
        gdrive_dir = Path(args.gdrive_dir)
        if gdrive_dir.exists():
            target_file = gdrive_dir / output_path.name
            shutil.copy2(output_path, target_file)
            logger.info("☁️ Synced updated dataset to Google Drive: %s", target_file)
    else:
        logger.info("No new unique verified samples found from scanned sources.")

    print("\n" + "=" * 60)
    print("DATAMATE SFT EXPANSION SUMMARY")
    print("=" * 60)
    print(f"Previous sample count : {len(existing_records) - len(newly_accepted)}")
    print(f"Newly accepted samples: {len(newly_accepted)}")
    print(f"Total verified samples: {len(existing_records)}")
    print(f"Output dataset path   : {output_path.resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
