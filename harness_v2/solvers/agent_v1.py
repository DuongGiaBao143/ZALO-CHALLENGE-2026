"""Solver M1: harness_v2.agent nối với một server vLLM/Ollama kiểu OpenAI.

Env: HV2_BASE_URL (mặc định http://127.0.0.1:8000/v1), HV2_MODEL, HV2_MAX_TOKENS (4096), HV2_TIMEOUT (600), HV2_MAX_STEPS (20),
HV2_CATALOG=0 để tắt mục lục dữ liệu, HV2_CHALLENGES=0 để tắt chặn chốt khi còn nguồn chưa dùng, HV2_REVIEW=1 để rà soát cuối mọi đáp án, HV2_THINK=0 để tắt chế độ suy nghĩ qua chat_template_kwargs, HV2_TEMPERATURE (0), HV2_TRACE_DIR để lưu trace từng câu."""
from __future__ import annotations

import functools
import json
import os
from pathlib import Path

from harness_v2.agent import Config, run_agent
from harness_v2.llm import chat


def make_llm():
    base, model = os.environ.get("HV2_BASE_URL", "http://127.0.0.1:8000/v1"), os.environ.get("HV2_MODEL", "ornith")
    temp = float(os.environ.get("HV2_TEMPERATURE", "0"))

    def llm(messages, tools, *, max_tokens, timeout, extra_body):
        return chat(base, model, messages, tools, max_tokens=max_tokens, temperature=temp, timeout=timeout, extra_body=extra_body)
    return llm


def make_config() -> Config:
    extra = {"chat_template_kwargs": {"enable_thinking": False}} if os.environ.get("HV2_THINK", "1") == "0" else {}
    return Config(max_steps=int(os.environ.get("HV2_MAX_STEPS", 20)), max_tokens=int(os.environ.get("HV2_MAX_TOKENS", 4096)),
                  timeout=float(os.environ.get("HV2_TIMEOUT", 600)), extra_body=extra,
                  catalog=os.environ.get("HV2_CATALOG", "1") != "0", max_challenges=int(os.environ.get("HV2_CHALLENGES", 1)), review=os.environ.get("HV2_REVIEW", "0") == "1")


@functools.lru_cache(maxsize=1)
def _setup():
    return make_llm(), make_config()


def solve(item: dict, split_dir: Path) -> dict:
    llm, cfg = _setup()
    res = run_agent(item, split_dir, llm, cfg)
    trace_dir = os.environ.get("HV2_TRACE_DIR")
    if trace_dir:
        Path(trace_dir).mkdir(parents=True, exist_ok=True)
        (Path(trace_dir) / f"{item['id']}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    res.pop("trace", None)   # trace dài, không đưa vào predictions.jsonl
    return res
