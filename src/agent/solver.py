"""Main DataMate Agent with Self-Correction Loop, Abstain Gatekeeper, and Per-Question Logging."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.agent.prompts import (
    SYSTEM_PROMPT,
    build_error_correction_prompt,
    build_user_prompt,
)
from src.agent.sandbox import extract_python_code, run_python_in_sandbox
from src.postprocess.normalizer import format_answer_payload
from src.profiler.business_loader import format_profile_for_prompt, profile_business_package
from src.schemas import AnswerType, BusinessProfile, QuestionItem, SubmissionItem
from src.time_resolver.calendar_utils import load_shared_context, resolve_relative_dates

logger = logging.getLogger(__name__)


class DataMateAgent:
    """End-to-end Tabular QA Agent for Zalo AI Challenge 2026."""

    def __init__(self, config: Dict[str, Any], data_dir: str | Path) -> None:
        self.config = config
        self.data_dir = Path(data_dir)
        self.model_cfg = config.get("model", {})
        self.agent_cfg = config.get("agent", {})
        self.paths_cfg = config.get("paths", {})

        self.backend = self.model_cfg.get("backend", "dry_run")
        self.max_retries = int(self.agent_cfg.get("max_retries", 2))
        self.sandbox_timeout = int(self.agent_cfg.get("sandbox_timeout_sec", 15))
        self.work_dir = str(self.paths_cfg.get("work_dir", "/tmp/datamate_work"))

        # Cache business profiles so we only profile each business once
        self._profile_cache: Dict[str, BusinessProfile] = {}
        self.shared_context = load_shared_context(self.data_dir)

        self.llm = None
        self.sampling_params = None
        if self.backend == "vllm":
            self._init_vllm()

    def _init_vllm(self) -> None:
        """Initialize offline vLLM engine (for 2 x NVIDIA RTX 5090 container)."""
        from vllm import LLM, SamplingParams

        model_name = self.model_cfg["name_or_path"]
        logger.info("Loading vLLM model: %s", model_name)
        self.llm = LLM(
            model=model_name,
            tensor_parallel_size=int(self.model_cfg.get("tensor_parallel_size", 2)),
            gpu_memory_utilization=float(self.model_cfg.get("gpu_memory_utilization", 0.90)),
            max_model_len=int(self.model_cfg.get("max_model_len", 16384)),
            dtype=self.model_cfg.get("dtype", "bfloat16"),
            trust_remote_code=True,
        )
        self.sampling_params = SamplingParams(
            temperature=float(self.model_cfg.get("temperature", 0.0)),
            top_p=float(self.model_cfg.get("top_p", 1.0)),
            seed=int(self.model_cfg.get("seed", 42)),
            max_tokens=int(self.model_cfg.get("max_tokens", 2048)),
        )

    def _get_business_profile(self, business_id: str) -> BusinessProfile:
        if business_id not in self._profile_cache:
            # Official package structure from data.md: <split>/data/<business_id>/
            candidates = [
                self.data_dir / "data" / business_id,
                self.data_dir / "businesses" / business_id,
                self.data_dir / business_id,
            ]
            b_dir = next((p for p in candidates if p.exists()), candidates[0])
            self._profile_cache[business_id] = profile_business_package(
                business_dir=b_dir,
                business_id=business_id,
                max_sample_rows=int(self.agent_cfg.get("max_sample_rows", 5)),
                max_unique_categorical=int(self.agent_cfg.get("max_unique_categorical", 25)),
            )
        return self._profile_cache[business_id]

    def _generate_llm_response(self, messages: List[Dict[str, str]]) -> str:
        """Generate response from vLLM (or dry_run fallback for CPU pipeline testing)."""
        if self.backend == "dry_run" or self.llm is None:
            return (
                "```python\n"
                'print(json.dumps({"type": "abstain", "answer": None}, ensure_ascii=False))\n'
                "```"
            )

        outputs = self.llm.chat(messages=[messages], sampling_params=self.sampling_params)
        return outputs[0].outputs[0].text

    def answer_question_with_trace(
        self, item: QuestionItem
    ) -> Tuple[SubmissionItem, Dict[str, Any]]:
        """Solve a single QuestionItem and return both SubmissionItem and per-question log trace."""
        t0 = time.time()
        trace: Dict[str, Any] = {
            "id": item.id,
            "business_id": item.business_id,
            "question": item.question,
            "as_of_date": item.as_of_date,
            "attempts": [],
        }

        profile = self._get_business_profile(item.business_id)
        if profile.error:
            logger.warning("Business profile error for %s: %s", item.id, profile.error)
            sub = SubmissionItem.abstain(item.id)
            trace["final_answer"] = sub.to_dict()
            trace["elapsed_time_sec"] = round(time.time() - t0, 4)
            trace["error"] = profile.error
            return sub, trace

        try:
            rel_dates = resolve_relative_dates(item.as_of_date)
        except Exception as exc:
            logger.warning("Invalid as_of_date for %s (%s): %s", item.id, item.as_of_date, exc)
            rel_dates = {"as_of_date": item.as_of_date}

        calendar_path = self.shared_context.get("calendar_path", "")
        schema_md = format_profile_for_prompt(profile)
        user_prompt = build_user_prompt(
            question=item.question,
            as_of_date=item.as_of_date,
            relative_dates=rel_dates,
            schema_markdown=schema_md,
            rulebook_text=self.shared_context.get("rulebook_text", ""),
            calendar_path=calendar_path,
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        for attempt in range(self.max_retries + 1):
            llm_reply = self._generate_llm_response(messages)
            code = extract_python_code(llm_reply)
            if not code:
                trace["attempts"].append(
                    {
                        "attempt": attempt + 1,
                        "generated_code": None,
                        "error": "No Python code block found in LLM response.",
                    }
                )
                messages.append({"role": "assistant", "content": llm_reply})
                messages.append(
                    {
                        "role": "user",
                        "content": "Bạn chưa xuất khối code ```python ... ```. Hãy viết code Python để tính toán và in ra JSON.",
                    }
                )
                continue

            sandbox_res = run_python_in_sandbox(
                code=code,
                business_dir=profile.business_dir,
                calendar_path=calendar_path,
                work_dir=self.work_dir,
                timeout_sec=self.sandbox_timeout,
            )

            trace["attempts"].append(
                {
                    "attempt": attempt + 1,
                    "generated_code": code,
                    "stdout": sandbox_res.stdout,
                    "stderr": sandbox_res.stderr,
                    "success": sandbox_res.success,
                    "error_message": sandbox_res.error_message,
                }
            )

            if sandbox_res.success and sandbox_res.parsed_output is not None:
                raw_type = sandbox_res.parsed_output.get("type", AnswerType.ABSTAIN.value)
                raw_ans = sandbox_res.parsed_output.get("answer")
                clean_type, clean_ans = format_answer_payload(
                    raw_type, raw_ans, fallback_to_abstain=True
                )
                sub = SubmissionItem(id=item.id, type=clean_type, answer=clean_ans)
                trace["final_answer"] = sub.to_dict()
                trace["elapsed_time_sec"] = round(time.time() - t0, 4)
                return sub, trace

            logger.info(
                "Question %s attempt %d/%d failed: %s",
                item.id,
                attempt + 1,
                self.max_retries + 1,
                sandbox_res.error_message,
            )
            messages.append({"role": "assistant", "content": llm_reply})
            messages.append(
                {
                    "role": "user",
                    "content": build_error_correction_prompt(code, sandbox_res.error_message),
                }
            )

        sub = SubmissionItem.abstain(item.id)
        trace["final_answer"] = sub.to_dict()
        trace["elapsed_time_sec"] = round(time.time() - t0, 4)
        return sub, trace

    def answer_question(self, item: QuestionItem) -> SubmissionItem:
        sub, _ = self.answer_question_with_trace(item)
        return sub
