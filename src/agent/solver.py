"""Main DataMate single-model agent with multi-turn bounded execution loop and offline backends."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.agent.prompts import (
    SYSTEM_PROMPT,
    build_error_correction_prompt,
    build_observation_prompt,
    build_user_prompt,
)
from src.agent.sandbox import SandboxResult, extract_python_code, run_python_in_sandbox
from src.postprocess.normalizer import format_answer_payload
from src.profiler.business_loader import format_profile_for_prompt, profile_business_package
from src.schemas import (
    AnswerType,
    BusinessProfile,
    ProtocolKind,
    QuestionItem,
    SubmissionItem,
    VALID_ANSWER_TYPES,
)
from src.time_resolver.calendar_utils import load_shared_context, resolve_relative_dates

logger = logging.getLogger(__name__)

# Enforce offline HuggingFace environment unless explicitly configured for online mode
if os.environ.get("HF_HUB_OFFLINE") != "0":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"


# =====================================================================
# Offline Inference Backends
# =====================================================================

class BaseInferenceBackend(ABC):
    """Abstract base class for offline LLM backends."""

    @abstractmethod
    def generate(self, messages: List[Dict[str, str]]) -> str:
        """Generate assistant response given conversation message history."""
        raise NotImplementedError


def _validate_local_model_directory(model_dir_str: Optional[str]) -> Path:
    """Strictly validate that local offline model weights directory exists and is complete.

    Verifies:
      1. Directory exists and contains 'config.json'.
      2. At least one supported tokenizer asset exists:
         - 'tokenizer.json', or
         - 'tokenizer.model', or
         - 'vocab.json' + 'merges.txt'.
      3. Model weights or index files exist:
         - Any '.safetensors' or '.bin' weight files, or
         - 'model.safetensors.index.json' / 'pytorch_model.bin.index.json' whose
           listed weight shards all exist locally within the directory.

    Never falls back to online downloading.
    """
    if not model_dir_str or not str(model_dir_str).strip():
        if os.environ.get("DATAMATE_ALLOW_ONLINE") == "1":
            return Path("Qwen/Qwen2.5-Coder-7B-Instruct")
        raise FileNotFoundError(
            "Local model directory ('local_model_dir') is not configured. "
            "Offline inference requires an existing local directory containing weights and config."
        )

    model_path = Path(model_dir_str).resolve()
    if not model_path.exists() or not model_path.is_dir():
        if os.environ.get("DATAMATE_ALLOW_ONLINE") == "1":
            return Path(model_dir_str)
        raise FileNotFoundError(
            f"Offline model weights directory not found: {model_path}. "
            "Please ensure model weights are downloaded locally before running."
        )

    # 1. Config presence check
    config_file = model_path / "config.json"
    if not config_file.exists():
        raise FileNotFoundError(
            f"Model directory {model_path} is missing 'config.json'. Offline weights appear incomplete."
        )

    # 2. Tokenizer asset presence check
    has_tokenizer = (
        (model_path / "tokenizer.json").exists()
        or (model_path / "tokenizer.model").exists()
        or ((model_path / "vocab.json").exists() and (model_path / "merges.txt").exists())
    )
    if not has_tokenizer:
        raise FileNotFoundError(
            f"Model directory {model_path} is missing tokenizer assets. "
            "Expected 'tokenizer.json', 'tokenizer.model', or 'vocab.json' + 'merges.txt'."
        )

    # 3. Model weight presence check (.safetensors, .bin, or valid index with existing shards)
    index_files = [
        model_path / idx_name
        for idx_name in ("model.safetensors.index.json", "pytorch_model.bin.index.json")
        if (model_path / idx_name).exists()
    ]

    if index_files:
        # A sharded index is present: ALL referenced local shards must exist and be valid
        for idx_path in index_files:
            try:
                with idx_path.open("r", encoding="utf-8") as f:
                    idx_data = json.load(f)
            except Exception as exc:
                raise FileNotFoundError(
                    f"Index file {idx_path.name} in {model_path} is malformed or unreadable: {exc}"
                ) from exc

            if not isinstance(idx_data, dict):
                raise FileNotFoundError(f"Index file {idx_path.name} in {model_path} is not a valid JSON dict.")

            weight_map = idx_data.get("weight_map")
            if not weight_map or not isinstance(weight_map, dict):
                raise FileNotFoundError(
                    f"Index file {idx_path.name} in {model_path} has missing or empty 'weight_map'."
                )

            shards = set(weight_map.values())
            for shard in shards:
                if not isinstance(shard, str) or not shard.strip():
                    raise FileNotFoundError(f"Invalid shard name in index {idx_path.name}: {shard!r}")
                if ".." in shard or shard.startswith("/") or shard.startswith("\\"):
                    raise FileNotFoundError(
                        f"Weight shard {shard!r} listed in index {idx_path.name} attempts directory traversal."
                    )
                shard_path = (model_path / shard).resolve()
                try:
                    shard_path.relative_to(model_path)
                except ValueError:
                    raise FileNotFoundError(
                        f"Weight shard {shard!r} listed in index {idx_path.name} resolves outside model directory."
                    )
                if not shard_path.exists():
                    raise FileNotFoundError(
                        f"Weight shard {shard} listed in index {idx_path.name} was not found in {model_path}."
                    )
    else:
        # Standalone weight files check (when no index is present)
        standalone_weights = [
            p.name
            for p in model_path.iterdir()
            if p.is_file() and p.suffix in (".safetensors", ".bin") and not p.name.endswith(".index.json")
        ]
        if not standalone_weights:
            raise FileNotFoundError(
                f"Model directory {model_path} contains config and tokenizer but no model weight files "
                "(expected '.safetensors', '.bin', or valid index file with all shards)."
            )

    return model_path


def _resolve_and_repair_adapter(adapter_dir: Optional[Union[str, Path]]) -> Tuple[Optional[Path], int]:
    """Resolve adapter directory and automatically remove activation-checkpoint wrappers if present."""
    if not adapter_dir:
        return None, 16
    adapter_path = Path(adapter_dir).resolve()
    if not (adapter_path / "adapter_config.json").is_file():
        if (adapter_path / "repaired" / "adapter_config.json").is_file():
            adapter_path = adapter_path / "repaired"
        elif (adapter_path / "final_adapter" / "adapter_config.json").is_file():
            adapter_path = adapter_path / "final_adapter"
        else:
            raise FileNotFoundError(f"Adapter config missing: {adapter_path}")
    elif (adapter_path / "repaired" / "adapter_config.json").is_file():
        adapter_path = adapter_path / "repaired"

    adapter_config = json.loads((adapter_path / "adapter_config.json").read_text(encoding="utf-8"))
    adapter_rank = int(adapter_config.get("r", 16))

    weights_file = adapter_path / "adapter_model.safetensors"
    if weights_file.is_file():
        from safetensors import safe_open
        with safe_open(str(weights_file), framework="np") as weights:
            has_wrapper = any("_checkpoint_wrapped_module" in key for key in weights.keys())
        if has_wrapper:
            repaired_dir = adapter_path / "repaired"
            repaired_weights = repaired_dir / "adapter_model.safetensors"
            repaired_config = repaired_dir / "adapter_config.json"
            if not (repaired_weights.is_file() and repaired_config.is_file()):
                repaired_dir.mkdir(parents=True, exist_ok=True)
                import shutil
                for item in adapter_path.iterdir():
                    if item.is_file() and item.name != "adapter_model.safetensors":
                        shutil.copy2(item, repaired_dir / item.name)
                from safetensors.torch import load_file, save_file
                state = load_file(str(weights_file), device="cpu")
                clean_state = {key.replace("_checkpoint_wrapped_module.", ""): val for key, val in state.items()}
                save_file(clean_state, str(repaired_weights))
                logger.info("Automatically repaired adapter wrappers to: %s", repaired_dir)
            adapter_path = repaired_dir

    return adapter_path, adapter_rank


class VLLMBackend(BaseInferenceBackend):
    """Offline vLLM backend for 2 x NVIDIA RTX 5090 reference server."""

    def __init__(self, model_cfg: Dict[str, Any]) -> None:
        local_dir = model_cfg.get("local_model_dir") or model_cfg.get("name_or_path")
        # Validate local directory BEFORE importing heavy engine
        model_path = _validate_local_model_directory(local_dir)
        adapter_dir = model_cfg.get('adapter_path') or model_cfg.get('adapter_dir')
        adapter_path, adapter_rank = _resolve_and_repair_adapter(adapter_dir)
        self.lora_request = None

        dtype = str(model_cfg.get("dtype", "bfloat16")).lower()
        if dtype not in ("bfloat16", "float16", "float32", "auto"):
            raise ValueError(f"Unsupported dtype for vLLM: {dtype!r}")

        try:
            from vllm import LLM, SamplingParams
        except ImportError as exc:
            raise ImportError(
                "vLLM is not installed. To run with backend='vllm', install vllm>=0.7.2 "
                "in a CUDA >= 12.8 environment."
            ) from exc

        if adapter_path:
            from vllm.lora.request import LoRARequest
            self.lora_request = LoRARequest('datamate', 1, str(adapter_path))

        logger.info("Initializing offline vLLM backend with model path: %s", model_path)
        # Low-VRAM GPUs (e.g. single T4): in-flight bitsandbytes 4-bit, LoRA still supported.
        quant_kwargs = {'quantization': 'bitsandbytes'} if model_cfg.get('load_in_4bit') else {}
        self.llm = LLM(
            **quant_kwargs,
            model=str(model_path),
            tensor_parallel_size=int(model_cfg.get("tensor_parallel_size", 1)),
            gpu_memory_utilization=float(model_cfg.get("gpu_memory_utilization", 0.90)),
            max_model_len=int(model_cfg.get("max_model_len", 16384)),
            dtype=dtype,
            trust_remote_code=True,
            seed=int(model_cfg.get('seed', 42)),
            enable_lora=bool(adapter_path),
            max_lora_rank=max(16, adapter_rank),
            enable_prefix_caching=bool(model_cfg.get('enable_prefix_caching', True)),
            enforce_eager=bool(model_cfg.get('enforce_eager', False)),
            max_num_seqs=int(model_cfg.get('max_num_seqs', 1)),
        )
        self.sampling_params = SamplingParams(
            temperature=float(model_cfg.get("temperature", 0.0)),
            top_p=float(model_cfg.get("top_p", 1.0)),
            seed=int(model_cfg.get("seed", 42)),
            max_tokens=int(model_cfg.get("max_tokens", 2048)),
        )

    def generate(self, messages: List[Dict[str, str]]) -> str:
        outputs = self.llm.chat(messages=[messages], sampling_params=self.sampling_params,
                                lora_request=self.lora_request, use_tqdm=False)
        return outputs[0].outputs[0].text


class TransformersBackend(BaseInferenceBackend):
    """Offline HuggingFace Transformers backend (supported for Kaggle 2xT4 or single GPU/CPU)."""

    def __init__(self, model_cfg: Dict[str, Any]) -> None:
        local_dir = model_cfg.get("local_model_dir") or model_cfg.get("name_or_path")
        # Validate local directory BEFORE importing heavy libraries
        model_path = _validate_local_model_directory(local_dir)

        dtype_str = str(model_cfg.get("dtype", "float16")).lower()
        if dtype_str not in ("bfloat16", "float16", "float32", "auto"):
            raise ValueError(f"Unsupported dtype for Transformers backend: {dtype_str!r}")

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise ImportError(
                "transformers or torch is not installed. To run with backend='transformers', "
                "install torch and transformers."
            ) from exc

        logger.info("Initializing offline Transformers backend with model path: %s", model_path)
        torch_dtype = getattr(torch, dtype_str) if hasattr(torch, dtype_str) else torch.float16

        self.tokenizer = AutoTokenizer.from_pretrained(
            str(model_path),
            local_files_only=(os.environ.get("DATAMATE_ALLOW_ONLINE") != "1"),
            trust_remote_code=True,
        )

        load_kwargs: Dict[str, Any] = {
            "torch_dtype": torch_dtype,
            "device_map": model_cfg.get("device_map", "auto"),
            "local_files_only": (os.environ.get("DATAMATE_ALLOW_ONLINE") != "1"),
            "trust_remote_code": True,
        }

        # Support explicit max_memory map for multi-GPU setups (e.g. Kaggle 2 x T4)
        max_mem = model_cfg.get("max_memory")
        if max_mem:
            # Format keys if provided as integer strings or ints
            formatted_max_mem = {}
            for k, v in max_mem.items():
                try:
                    formatted_max_mem[int(k)] = v
                except ValueError:
                    formatted_max_mem[k] = v
            load_kwargs["max_memory"] = formatted_max_mem

        if model_cfg.get('attn_implementation'):
            load_kwargs['attn_implementation'] = model_cfg['attn_implementation']
        if model_cfg.get('load_in_4bit'):
            from transformers import BitsAndBytesConfig
            load_kwargs['quantization_config'] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type='nf4',
            )
            load_kwargs.pop('torch_dtype', None)
        elif model_cfg.get('load_in_8bit'):
            load_kwargs['load_in_8bit'] = True
            load_kwargs.pop('torch_dtype', None)
        self.model = AutoModelForCausalLM.from_pretrained(str(model_path), **load_kwargs)

        adapter_path = model_cfg.get("adapter_path") or model_cfg.get("adapter_dir")
        if adapter_path:
            from peft import PeftModel

            adapter_resolved, _ = _resolve_and_repair_adapter(adapter_path)
            logger.info("Loading LoRA adapter from: %s", adapter_resolved)
            self.model = PeftModel.from_pretrained(
                self.model,
                str(adapter_resolved),
                local_files_only=(os.environ.get("DATAMATE_ALLOW_ONLINE") != "1"),
            )

        self.max_tokens = int(model_cfg.get("max_tokens", 2048))
        self.temperature = float(model_cfg.get("temperature", 0.0))
        self.max_model_len = int(model_cfg.get("max_model_len", 16384))
        if self.max_model_len <= 0:
            raise ValueError(f"max_model_len must be a positive integer, got {self.max_model_len}")
        timeout = model_cfg.get('max_generation_time_sec')
        self.max_generation_time_sec = None if timeout is None else float(timeout)
        if self.max_generation_time_sec is not None and not 0 < self.max_generation_time_sec < float('inf'):
            raise ValueError('max_generation_time_sec must be finite and positive')

    def generate(self, messages: List[Dict[str, str]]) -> str:
        import torch

        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer(prompt, return_tensors="pt")
        input_tokens_count = int(inputs.input_ids.shape[1])
        remaining_tokens = self.max_model_len - input_tokens_count
        if remaining_tokens <= 0:
            raise ValueError(
                f"Context budget exceeded: prompt has {input_tokens_count} tokens, "
                f"leaving no generation room within max_model_len of {self.max_model_len}."
            )
        generation_tokens = min(self.max_tokens, remaining_tokens)
        if generation_tokens < self.max_tokens:
            logger.warning(
                "Reducing generation budget from %d to %d tokens for a %d-token prompt (context limit %d); prompt preserved",
                self.max_tokens, generation_tokens, input_tokens_count, self.max_model_len,
            )

        inputs = inputs.to(self.model.device)
        with torch.no_grad():
            gen_kwargs = {
                "max_new_tokens": generation_tokens,
                "do_sample": self.temperature > 0.0,
                "pad_token_id": self.tokenizer.eos_token_id,
            }
            if self.temperature > 0.0:
                gen_kwargs["temperature"] = self.temperature
            if self.max_generation_time_sec is not None:
                # Transformers checks this after a generation step; this is not a hard process timeout.
                gen_kwargs['max_time'] = self.max_generation_time_sec
            outputs = self.model.generate(**inputs, **gen_kwargs)

        generated_ids = outputs[0][inputs.input_ids.shape[1] :]
        return self.tokenizer.decode(generated_ids, skip_special_tokens=True)


class DryRunBackend(BaseInferenceBackend):
    """Explicit dry_run backend for local testing of I/O pipelines without GPU."""

    def __init__(self, model_cfg: Dict[str, Any]) -> None:
        self.default_reply = model_cfg.get(
            "dry_run_reply",
            (
                "```python\n"
                'print(json.dumps({"kind": "final", "type": "abstain", "answer": None, "evidence": "dry_run mode"}, ensure_ascii=False))\n'
                "```"
            ),
        )

    def generate(self, messages: List[Dict[str, str]]) -> str:
        return self.default_reply


class ScriptedBackend(BaseInferenceBackend):
    """Deterministic scripted backend for unit tests and multi-turn verification."""

    def __init__(self, responses: List[str]) -> None:
        self.responses = list(responses)
        self.idx = 0

    def generate(self, messages: List[Dict[str, str]]) -> str:
        if self.idx < len(self.responses):
            resp = self.responses[self.idx]
            self.idx += 1
            return resp
        return (
            "```python\n"
            'print(json.dumps({"kind": "final", "type": "abstain", "answer": None, "evidence": "scripted responses exhausted"}, ensure_ascii=False))\n'
            "```"
        )


def create_inference_backend(model_cfg: Dict[str, Any]) -> BaseInferenceBackend:
    """Factory to instantiate the configured inference backend. Fails clearly on unknown backend."""
    backend_name = str(model_cfg.get("backend", "vllm")).lower().strip()
    if backend_name == "vllm":
        return VLLMBackend(model_cfg)
    elif backend_name == "transformers":
        return TransformersBackend(model_cfg)
    elif backend_name == "dry_run":
        return DryRunBackend(model_cfg)
    elif backend_name == "scripted":
        scripted_replies = model_cfg.get("scripted_responses", [])
        return ScriptedBackend(scripted_replies)
    else:
        raise ValueError(
            f"Unsupported model backend: '{backend_name}'. "
            "Supported backends are: 'vllm', 'transformers', 'dry_run', 'scripted'."
        )


# =====================================================================
# Main Agent Solver
# =====================================================================

def resolve_business_path(split_dir: Path, business_id: str) -> Path:
    """Safely resolve <split>/data/<business_id> preventing path traversal.

    Traversals such as '..', '/', absolute paths are rejected.
    """
    bid = str(business_id).strip()
    if not re.match(r"^[A-Za-z0-9_\-]+$", bid):
        raise ValueError(f"Path traversal or invalid characters detected in business_id: {bid!r}")

    split_dir_resolved = split_dir.resolve()

    candidates = [
        split_dir_resolved / "data" / bid,
        split_dir_resolved / "businesses" / bid,
        split_dir_resolved / bid,
    ]

    for candidate in candidates:
        cand_resolved = candidate.resolve()
        try:
            cand_resolved.relative_to(split_dir_resolved)
        except ValueError:
            raise ValueError(
                f"Resolved business directory {cand_resolved} is outside split dir {split_dir_resolved}"
            )
        if cand_resolved.exists() and cand_resolved.is_dir():
            return cand_resolved

    default_path = (split_dir_resolved / "data" / bid).resolve()
    return default_path


class DataMateAgent:
    """Single-model Agent (Qwen2.5-Coder-7B-Instruct) with multi-turn code execution and guardrails."""

    def __init__(
        self,
        config: Dict[str, Any],
        data_dir: str | Path,
        backend: Optional[BaseInferenceBackend] = None,
    ) -> None:
        self.config = config
        self.data_dir = Path(data_dir).resolve()
        self.model_cfg = config.get("model", {})
        self.agent_cfg = config.get("agent", {})
        self.paths_cfg = config.get("paths", {})

        # Validate positive limits
        self.max_turns = int(self.agent_cfg.get("max_turns", 3))
        if self.max_turns < 1:
            raise ValueError(f"max_turns must be a positive integer >= 1, got {self.max_turns}")

        self.max_code_executions = int(self.agent_cfg.get("max_code_executions", 3))
        if self.max_code_executions < 1:
            raise ValueError(f"max_code_executions must be a positive integer >= 1, got {self.max_code_executions}")

        self.sandbox_timeout = int(self.agent_cfg.get("sandbox_timeout_sec", 15))
        if self.sandbox_timeout < 1:
            raise ValueError(f"sandbox_timeout_sec must be positive integer >= 1, got {self.sandbox_timeout}")

        self.max_sample_rows = int(self.agent_cfg.get("max_sample_rows", 5))
        if self.max_sample_rows < 0:
            raise ValueError(f"max_sample_rows must be non-negative, got {self.max_sample_rows}")

        self.max_unique_categorical = int(self.agent_cfg.get("max_unique_categorical", 25))
        if self.max_unique_categorical < 0:
            raise ValueError(f"max_unique_categorical must be non-negative, got {self.max_unique_categorical}")

        self.work_dir = str(self.paths_cfg.get("work_dir", "/tmp/datamate_work"))

        # Cache question-independent business profiles
        self._profile_cache: Dict[str, BusinessProfile] = {}
        self.shared_context = load_shared_context(self.data_dir)

        # Inference backend
        if backend is not None:
            self.backend = backend
        else:
            self.backend = create_inference_backend(self.model_cfg)

    def _get_business_profile(self, business_id: str) -> BusinessProfile:
        if business_id not in self._profile_cache:
            try:
                b_dir = resolve_business_path(self.data_dir, business_id)
            except ValueError as val_err:
                return BusinessProfile(
                    business_id=business_id,
                    business_dir="",
                    readme_text="",
                    error=str(val_err),
                )

            self._profile_cache[business_id] = profile_business_package(
                business_dir=b_dir,
                business_id=business_id,
                max_sample_rows=self.max_sample_rows,
                max_unique_categorical=self.max_unique_categorical,
            )
        return self._profile_cache[business_id]

    def answer_question_with_trace(
        self, item: QuestionItem
    ) -> Tuple[SubmissionItem, Dict[str, Any]]:
        """Execute multi-turn agent interaction for a QuestionItem and return (SubmissionItem, trace)."""
        t0 = time.time()
        trace: Dict[str, Any] = {
            "id": item.id,
            "business_id": item.business_id,
            "question": item.question,
            "as_of_date": item.as_of_date,
            "system_prompt": SYSTEM_PROMPT,
            "attempts": [],
        }

        # 1. Validate question metadata
        try:
            item.validate()
        except Exception as exc:
            logger.warning("Invalid question metadata for %s: %s", item.id, exc)
            sub = SubmissionItem.abstain(item.id, reason=f"Metadata error: {exc}")
            trace["final_answer"] = sub.to_dict()
            trace["elapsed_time_sec"] = round(time.time() - t0, 4)
            trace["error"] = str(exc)
            return sub, trace

        # 2. Retrieve business profile
        profile = self._get_business_profile(item.business_id)
        if profile.error:
            logger.warning("Business profile error for %s: %s", item.id, profile.error)
            sub = SubmissionItem.abstain(item.id, reason=f"Profile error: {profile.error}")
            trace["final_answer"] = sub.to_dict()
            trace["elapsed_time_sec"] = round(time.time() - t0, 4)
            trace["error"] = profile.error
            return sub, trace

        # 3. Resolve relative dates
        try:
            rel_dates = resolve_relative_dates(item.as_of_date)
        except Exception as exc:
            logger.warning("Invalid as_of_date for %s (%s): %s", item.id, item.as_of_date, exc)
            rel_dates = {"as_of_date": item.as_of_date}

        calendar_path = self.shared_context.get("calendar_path", "")
        schema_md = format_profile_for_prompt(profile, compact=True)
        rulebook_text = self.shared_context.get("rulebook_text", "")
        user_prompt = build_user_prompt(
            question=item.question,
            as_of_date=item.as_of_date,
            relative_dates=rel_dates,
            schema_markdown=schema_md,
            rulebook_text=rulebook_text,
            calendar_path=calendar_path,
        )
        trace["initial_user_prompt"] = user_prompt

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        trace["messages"] = [dict(m) for m in messages]

        code_executions_count = 0

        # Multi-turn interaction loop
        for turn in range(self.max_turns):
            turn_idx = turn + 1
            turn_start = time.time()
            prompt_snapshot = [dict(m) for m in messages]

            try:
                llm_reply = self.backend.generate(messages)
            except Exception as be_exc:
                logger.error("Inference generation error on question %s: %s", item.id, be_exc)
                sub = SubmissionItem.abstain(item.id, reason=f"Backend generation error: {be_exc}")
                trace["final_answer"] = sub.to_dict()
                trace["elapsed_time_sec"] = round(time.time() - t0, 4)
                trace["error"] = str(be_exc)
                return sub, trace

            code = extract_python_code(llm_reply)

            # Case A: Model did not emit any Python code block
            if not code:
                attempt_record = {
                    "turn": turn_idx,
                    "prompt_messages": prompt_snapshot,
                    "llm_reply": llm_reply,
                    "generated_code": None,
                    "error": "No Python code block found in LLM response.",
                    "elapsed_sec": round(time.time() - turn_start, 4),
                }
                trace["attempts"].append(attempt_record)

                if turn == self.max_turns - 1:
                    break

                messages.append({"role": "assistant", "content": llm_reply})
                messages.append(
                    {
                        "role": "user",
                        "content": "Bạn chưa xuất khối code ```python ... ```. Hãy viết một script Python hoàn chỉnh để xử lý dữ liệu và in ra JSON protocol.",
                    }
                )
                trace["messages"] = [dict(m) for m in messages]
                continue

            # Case B: Code block present -> execute in bounded runner
            code_executions_count += 1
            sandbox_res: SandboxResult = run_python_in_sandbox(
                code=code,
                business_dir=profile.business_dir,
                calendar_path=calendar_path,
                work_dir=self.work_dir,
                timeout_sec=self.sandbox_timeout,
                as_of_date=item.as_of_date,
                rulebook_path=self.shared_context.get("rulebook_path", ""),
            )

            attempt_record = {
                "turn": turn_idx,
                "prompt_messages": prompt_snapshot,
                "llm_reply": llm_reply,
                "generated_code": code,
                "stdout": sandbox_res.stdout,
                "stderr": sandbox_res.stderr,
                "returncode": sandbox_res.returncode,
                "kind": sandbox_res.kind,
                "success": sandbox_res.success,
                "error_message": sandbox_res.error_message,
                "parsed_output": sandbox_res.parsed_output,
                "elapsed_sec": round(time.time() - turn_start, 4),
            }
            trace["attempts"].append(attempt_record)

            # Sub-case B1: Runner error or protocol violation
            if not sandbox_res.success or sandbox_res.kind == ProtocolKind.ERROR.value:
                if turn == self.max_turns - 1 or code_executions_count >= self.max_code_executions:
                    break

                messages.append({"role": "assistant", "content": llm_reply})
                messages.append(
                    {
                        "role": "user",
                        "content": build_error_correction_prompt(
                            sandbox_res.error_message,
                            sandbox_res.error_kind or "execution_error",
                            question=item.question,
                            as_of_date=item.as_of_date,
                        ),
                    }
                )
                trace["messages"] = [dict(m) for m in messages]
                continue

            # Sub-case B2: Discovery / Observation step
            if sandbox_res.kind == ProtocolKind.OBSERVATION.value:
                if turn == self.max_turns - 1 or code_executions_count >= self.max_code_executions:
                    logger.info("Question %s finished with observation on final turn -> abstain", item.id)
                    sub = SubmissionItem.abstain(item.id, reason="Observation-only on last turn")
                    trace["final_answer"] = sub.to_dict()
                    trace["elapsed_time_sec"] = round(time.time() - t0, 4)
                    return sub, trace

                obs_payload = sandbox_res.parsed_output or {}
                obs_data = obs_payload.get("data")
                obs_msg = str(obs_payload.get("message") or "")
                messages.append({"role": "assistant", "content": llm_reply})
                messages.append(
                    {
                        "role": "user",
                        "content": build_observation_prompt(
                            obs_data,
                            obs_msg,
                            question=item.question,
                            as_of_date=item.as_of_date,
                        ),
                    }
                )
                trace["messages"] = [dict(m) for m in messages]
                continue

            # Sub-case B3: Final Candidate Output -> Final Guard
            if sandbox_res.kind == ProtocolKind.FINAL.value and sandbox_res.parsed_output is not None:
                final_payload = sandbox_res.parsed_output
                raw_type = final_payload.get("type", AnswerType.ABSTAIN.value)
                raw_ans = final_payload.get("answer")
                evidence = final_payload.get("evidence")
                reason = final_payload.get("reason")

                try:
                    clean_type, clean_ans = format_answer_payload(
                        raw_type, raw_ans, fallback_to_abstain=False
                    )
                    sub = SubmissionItem(
                        id=item.id,
                        type=clean_type,
                        answer=clean_ans,
                        evidence=evidence,
                        reason=reason,
                    )
                    trace["final_answer"] = sub.to_dict()
                    trace["elapsed_time_sec"] = round(time.time() - t0, 4)
                    return sub, trace

                except Exception as guard_exc:
                    logger.info(
                        "Question %s final output validation failed: %s", item.id, guard_exc
                    )
                    if turn == self.max_turns - 1 or code_executions_count >= self.max_code_executions:
                        sub = SubmissionItem.abstain(
                            item.id, reason=f"Final answer validation failed: {guard_exc}"
                        )
                        trace["final_answer"] = sub.to_dict()
                        trace["elapsed_time_sec"] = round(time.time() - t0, 4)
                        return sub, trace

                    messages.append({"role": "assistant", "content": llm_reply})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"Định dạng kết quả cuối cùng không hợp lệ: {guard_exc}\n"
                                "Hãy sửa lại cách tính hoặc định dạng đáp án theo đúng yêu cầu đề bài và in ra JSON protocol."
                            ),
                        }
                    )
                    trace["messages"] = [dict(m) for m in messages]
                    continue

        # Exhausted turn budget or code execution budget -> Abstain (0 points)
        logger.info("Question %s exhausted turn budget (%d turns) -> abstain", item.id, self.max_turns)
        sub = SubmissionItem.abstain(item.id, reason="Exhausted maximum retry budget")
        trace["final_answer"] = sub.to_dict()
        trace["elapsed_time_sec"] = round(time.time() - t0, 4)
        return sub, trace

    def answer_question(self, item: QuestionItem) -> SubmissionItem:
        sub, _ = self.answer_question_with_trace(item)
        return sub
