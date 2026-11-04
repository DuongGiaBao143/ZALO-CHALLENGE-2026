"""Candidate trajectory generator and SFT pseudo-label collector.

Runs the DataMate single-model agent over train and validation splits to collect multi-turn
interaction traces. Evaluates each completed question trajectory with the official-style local
scorer, filtering candidates with strict execution and anti-leak criteria:
  1. Trajectory must conclude with an official 'correct' verdict (+1 pt).
  2. Target completion must be a successful executed step (observation or final).
  3. Fails/runtime errors stay in history to contextualize corrections, but never become targets.
  4. Script must perform genuine data access and not hardcode IDs or test/gold files.
  5. Examples are labeled 'execution-verified pseudo-labels' with complete provenance.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.agent.solver import DataMateAgent
from src.coder_training.io_utils import writable_output, read_unique_jsonl, tree_hash, select_questions
from src.eval.scorer import score_single_answer
from src.schemas import ProtocolKind, QuestionItem, SubmissionItem

logger = logging.getLogger(__name__)

# Keywords that indicate genuine data access in generated Python code
DATA_ACCESS_KEYWORDS = (
    "read_csv",
    "read_excel",
    "read_sql",
    "read_table",
    "sqlite3",
    ".connect(",
    "open(",
    "Path(",
    "os.listdir",
    "os.walk",
    "os.scandir",
    "glob.glob",
    "BUSINESS_DIR",
    "CALENDAR_PATH",
    "sqlite",
    ".cursor()",
)


def compute_provenance_hash(
    item: QuestionItem,
    model_name: str,
    config_dict: Dict[str, Any],
) -> str:
    """Compute deterministic provenance hash covering question data, model, and config."""
    payload = dict(question=asdict(item), model=model_name, config=config_dict)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()



def is_safe_code(code: str, question_id: str) -> Tuple[bool, str]:
    """Inspect candidate Python script for leaks, hardcoding, or no-op constant answers.

    Returns:
        (is_safe, reason): Boolean flag and explanation.
    """
    if not code or not code.strip():
        return False, "Empty code snippet"

    code_lower = code.lower()

    # 1. Anti-leak: accessing answers.jsonl or test splits
    leak_patterns = ["answers.jsonl", "public_test", "private"]
    for pat in leak_patterns:
        if pat in code_lower:
            return False, f"Code attempts to access forbidden resource: {pat}"

    # 2. Hardcoded question ID detection
    qid_clean = str(question_id).strip()
    if qid_clean and qid_clean in code:
        return False, f"Code hardcodes question id: {qid_clean}"

    # Generic check for question ID patterns like dev_001_q001 or train_001_q001
    if re.search(r"\b(train|dev|test)_[A-Za-z0-9]+_q\d+\b", code):
        return False, "Code contains hardcoded question identifier pattern"

    # 3. Constant-answer detection: code must perform some actual data access
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False, 'Invalid Python syntax'
    # shortcut: AST calls reject comment/string-only claims; semantic correctness needs manual audits.
    read_calls = {'read_csv', 'read_excel', 'read_sql', 'read_sql_query', 'read_table',
                  'open', 'read_text', 'read_bytes', 'listdir', 'walk', 'scandir', 'glob',
                  'rglob', 'iterdir', 'connect', 'execute', 'executemany'}
    has_data_access = any(isinstance(node, ast.Call) and
                          ((isinstance(node.func, ast.Name) and node.func.id in read_calls) or
                           (isinstance(node.func, ast.Attribute) and node.func.attr in read_calls))
                          for node in ast.walk(tree))
    if not has_data_access:
        return False, "Code emits output without any data file access (constant answer script)"

    return True, "ok"


@dataclass
class CollectorConfig:
    """Configuration for candidate generation and SFT extraction."""

    limit_train: Optional[int] = 200
    limit_val: Optional[int] = 40
    min_verified_train_examples: int = 16
    cache_dir: str = "cache/candidates"
    output_dir: str = "result/coder_sft"


@dataclass
class CollectorSummary:
    """Summary of candidate generation, local scoring, and SFT example filtering."""

    train_questions_attempted: int = 0
    val_questions_attempted: int = 0
    train_correct: int = 0
    train_abstain: int = 0
    train_wrong: int = 0
    val_correct: int = 0
    val_abstain: int = 0
    val_wrong: int = 0
    baseline_val_pa: float = 0.0
    val_by_type: Dict[str, Dict[str, int]] = field(default_factory=dict)
    total_steps_inspected: int = 0
    train_sft_examples_collected: int = 0
    val_sft_examples_collected: int = 0
    rejected_reasons: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def format_summary(self) -> str:
        lines = [
            "=" * 64,
            "DATAMATE CANDIDATE GENERATION & SFT COLLECTION SUMMARY",
            "=" * 64,
            f"Train Questions Attempted : {self.train_questions_attempted}",
            f"  - Correct               : {self.train_correct}",
            f"  - Abstain               : {self.train_abstain}",
            f"  - Wrong                 : {self.train_wrong}",
            f"Val Questions Attempted   : {self.val_questions_attempted}",
            f"  - Correct               : {self.val_correct}",
            f"  - Abstain               : {self.val_abstain}",
            f"  - Wrong                 : {self.val_wrong}",
            f"BASELINE VAL PA (Attempted): {self.baseline_val_pa:.4f}",
            "-" * 64,
            f"Total Steps Inspected     : {self.total_steps_inspected}",
            f"Train SFT Targets Accepted: {self.train_sft_examples_collected}",
            f"Val SFT Targets Accepted  : {self.val_sft_examples_collected}",
            "Rejection Reasons:",
        ]
        for reason, count in sorted(self.rejected_reasons.items()):
            lines.append(f"  * {reason:<36}: {count}")
        lines.append("=" * 64)
        return "\n".join(lines)


class CandidateCollector:
    """Manages candidate generation with cache/provenance and SFT filtering."""

    def __init__(
        self,
        agent: DataMateAgent,
        config: CollectorConfig,
        gold_answers: Dict[str, Dict[str, Any]],
        model_name: str = "Qwen2.5-Coder-7B-Instruct",
    ) -> None:
        self.agent = agent
        self.config = config
        self.gold_answers = gold_answers
        self.model_name = model_name
        self.raw_root = Path(agent.data_dir).resolve()
        self.cache_dir = writable_output(config.cache_dir, self.raw_root)
        self.output_dir = writable_output(config.output_dir, self.raw_root)
        # Hash once per immutable collection run, including rulebook, calendar, source and checkpoint bytes.
        self.run_config = json.loads(json.dumps(agent.config))
        self.run_config['_raw_hash'] = tree_hash(self.raw_root)
        self.run_config['_source_hash'] = tree_hash(Path(__file__).resolve().parents[1])
        model_dir = agent.config.get('model', {}).get('local_model_dir')
        self.run_config['_checkpoint_hash'] = tree_hash(model_dir) if model_dir else model_name
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _run_or_resume_question(
        self, item: QuestionItem
    ) -> Tuple[SubmissionItem, Dict[str, Any], str, int]:
        """Load from cache if provenance matches, otherwise run agent and cache."""
        if item.id not in self.gold_answers:
            raise ValueError(f'Missing gold for {item.id}')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', item.id):
            raise ValueError('Invalid question ID for cache filename')
        prov_hash = compute_provenance_hash(item, self.model_name, self.run_config)
        cache_file = self.cache_dir / f"{item.id}.json"

        if cache_file.exists():
            try:
                with cache_file.open("r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                if cached_data.get("provenance_hash") == prov_hash:
                    sub_item = SubmissionItem(
                        id=cached_data["sub"]["id"],
                        type=cached_data["sub"]["type"],
                        answer=cached_data["sub"].get("answer"),
                        evidence=cached_data["sub"].get("evidence"),
                        reason=cached_data["sub"].get("reason"),
                    )
                    verdict, score = score_single_answer(sub_item.to_dict(), self.gold_answers[item.id])
                    trace = cached_data["trace"]
                    return sub_item, trace, verdict, score
                else:
                    logger.debug("Provenance mismatch for %s; re-running agent.", item.id)
            except Exception as exc:
                logger.warning("Corrupted cache for %s (%s); re-running.", item.id, exc)

        # Run agent fresh
        sub_item, trace = self.agent.answer_question_with_trace(item)

        # Host-only score against gold answer
        gold_item = self.gold_answers.get(item.id)
        verdict, score = score_single_answer(sub_item.to_dict(), gold_item)

        # Save to cache with provenance
        cache_record = {
            "provenance_hash": prov_hash,
            "question_id": item.id,
            "sub": sub_item.to_dict(),
            "verdict": verdict,
            "score": score,
            "trace": trace,
            "timestamp": time.time(),
        }
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump(cache_record, f, ensure_ascii=False, indent=2)

        return sub_item, trace, verdict, score

    def extract_sft_examples_from_trace(
        self,
        item: QuestionItem,
        trace: Dict[str, Any],
        verdict: str,
        summary: CollectorSummary,
    ) -> List[Dict[str, Any]]:
        """Extract valid SFT step pairs from a trajectory.

        Strict acceptance rules:
          - Only trajectories whose final verdict is 'correct' (+1 pt).
          - Only attempts where execution succeeded (returncode == 0, kind observation/final).
          - Code must pass is_safe_code checks (no leak, no ID hardcoding, genuine data access).
        """
        accepted: List[Dict[str, Any]] = []

        if verdict != "correct":
            summary.rejected_reasons["final_answer_not_correct"] = (
                summary.rejected_reasons.get("final_answer_not_correct", 0) + 1
            )
            return accepted

        attempts = trace.get("attempts", [])
        for att in attempts:
            summary.total_steps_inspected += 1

            if not att.get("success"):
                summary.rejected_reasons["step_execution_failed"] = (
                    summary.rejected_reasons.get("step_execution_failed", 0) + 1
                )
                continue

            kind = att.get("kind")
            if kind not in (ProtocolKind.OBSERVATION.value, ProtocolKind.FINAL.value):
                summary.rejected_reasons["step_kind_invalid"] = (
                    summary.rejected_reasons.get("step_kind_invalid", 0) + 1
                )
                continue

            code = att.get("generated_code")
            if not code:
                summary.rejected_reasons["no_code_in_step"] = (
                    summary.rejected_reasons.get("no_code_in_step", 0) + 1
                )
                continue

            is_safe, reason = is_safe_code(code, item.id)
            if not is_safe:
                summary.rejected_reasons[f"code_rejected_{reason}"] = (
                    summary.rejected_reasons.get(f"code_rejected_{reason}", 0) + 1
                )
                continue

            prompt_messages = att.get("prompt_messages")
            llm_reply = att.get("llm_reply")
            if not prompt_messages or not llm_reply:
                summary.rejected_reasons["missing_messages_or_reply"] = (
                    summary.rejected_reasons.get("missing_messages_or_reply", 0) + 1
                )
                continue

            accepted.append(
                {
                    "question_id": item.id,
                    "business_id": item.business_id,
                    "turn": att.get("turn", 1),
                    "kind": kind,
                    "provenance": "execution-verified pseudo-label",
                    "prompt_messages": prompt_messages,
                    "target_completion": llm_reply,
                }
            )

        return accepted

    def process_split(
        self,
        questions_path: Path | str,
        split_name: str,
        limit: Optional[int],
        summary: CollectorSummary,
    ) -> List[Dict[str, Any]]:
        """Process a split of questions and collect verified SFT examples."""
        q_path = Path(questions_path).resolve()
        questions: List[QuestionItem] = []
        with q_path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if line:
                    questions.append(QuestionItem.from_dict(json.loads(line)))

        if split_name not in ('train', 'val'):
            raise ValueError('Unknown split')
        read_unique_jsonl(q_path)
        if any(q.id not in self.gold_answers for q in questions):
            raise ValueError('Missing gold coverage')
        if limit is not None and limit <= 0:
            raise ValueError('Question limit must be positive or None')
        questions = select_questions(questions, limit, self.agent.config.get('model', {}).get('seed', 42))

        sft_examples: List[Dict[str, Any]] = []

        val_total_score = 0
        for index, item in enumerate(questions, 1):
            started = time.monotonic()
            logger.info('Collect %s %d/%d: %s', split_name, index, len(questions), item.id)
            sub_item, trace, verdict, score = self._run_or_resume_question(item)

            if split_name == "train":
                summary.train_questions_attempted += 1
                if verdict == "correct":
                    summary.train_correct += 1
                elif verdict == "abstain":
                    summary.train_abstain += 1
                else:
                    summary.train_wrong += 1
            else:
                summary.val_questions_attempted += 1
                val_total_score += score
                if verdict == "correct":
                    summary.val_correct += 1
                elif verdict == "abstain":
                    summary.val_abstain += 1
                else:
                    summary.val_wrong += 1

                gold_item = self.gold_answers.get(item.id, {})
                ref_type = str(gold_item.get("type", "unknown")).lower()
                if ref_type not in summary.val_by_type:
                    summary.val_by_type[ref_type] = {"total": 0, "correct": 0, "abstain": 0, "wrong": 0}
                summary.val_by_type[ref_type]["total"] += 1
                summary.val_by_type[ref_type][verdict] += 1

            step_examples = self.extract_sft_examples_from_trace(item, trace, verdict, summary)
            sft_examples.extend(step_examples)
            logger.info('Collect %s %s: %s, %.1fs, accepted=%d, total_targets=%d',
                        split_name, item.id, verdict, time.monotonic() - started,
                        len(step_examples), len(sft_examples))

        if split_name == "val" and summary.val_questions_attempted > 0:
            # Baseline PA strictly over ATTEMPTED validation questions
            summary.baseline_val_pa = val_total_score / summary.val_questions_attempted

        if split_name == "train":
            summary.train_sft_examples_collected = len(sft_examples)
        else:
            summary.val_sft_examples_collected = len(sft_examples)

        return sft_examples

    def collect(
        self,
        train_questions_path: Path | str,
        val_questions_path: Path | str,
    ) -> CollectorSummary:
        """Execute full collection over train and validation splits."""
        train_rows = read_unique_jsonl(train_questions_path)
        val_rows = read_unique_jsonl(val_questions_path)
        if {q['business_id'] for q in train_rows} & {q['business_id'] for q in val_rows}:
            raise ValueError('Business leakage across SFT splits')
        if {q['id'] for q in train_rows} & {q['id'] for q in val_rows}:
            raise ValueError('Question leakage across SFT splits')
        if any(q['id'] not in self.gold_answers for q in train_rows + val_rows):
            raise ValueError('Missing gold coverage')
        summary = CollectorSummary()

        train_examples = self.process_split(
            train_questions_path,
            split_name="train",
            limit=self.config.limit_train,
            summary=summary,
        )

        val_examples = self.process_split(
            val_questions_path,
            split_name="val",
            limit=self.config.limit_val,
            summary=summary,
        )

        # Guard: check minimum verified training examples
        if len(train_examples) < self.config.min_verified_train_examples:
            raise ValueError(
                f"Too few execution-verified training examples collected: {len(train_examples)} "
                f"< {self.config.min_verified_train_examples}. Stopping clearly rather than training on empty or bad data."
            )

        if not val_examples:
            raise ValueError('No verified validation targets; increase generation budget before training')
        # Write out datasets
        train_sft_file = self.output_dir / "train_sft.jsonl"
        val_sft_file = self.output_dir / "val_sft.jsonl"
        summary_file = self.output_dir / "collector_summary.json"

        with train_sft_file.open("w", encoding="utf-8") as f:
            for ex in train_examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

        with val_sft_file.open("w", encoding="utf-8") as f:
            for ex in val_examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

        with summary_file.open("w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info(summary.format_summary())
        return summary
