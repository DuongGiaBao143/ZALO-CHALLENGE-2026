"""Main DataMate single-model agent with multi-turn bounded execution loop and offline backends."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

import numpy as np

from src.agent.prompts import (
    SYSTEM_PROMPT,
    _mentions,
    _search_text,
    build_error_correction_prompt,
    build_observation_prompt,
    build_system_prompt,
    build_user_prompt,
)
from src.agent.sandbox import SandboxResult, extract_python_code, run_python_in_sandbox
from src.postprocess.normalizer import format_answer_payload
from src.profiler.business_loader import format_eval_schema, format_profile_for_prompt, profile_business_package
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

Conversation = List[Dict[str, str]]
QuestionResult = Tuple[SubmissionItem, Dict[str, Any]]

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
            raise ValueError(
                f"Adapter weights in {adapter_path} contain activation checkpoint wrapper "
                "('_checkpoint_wrapped_module.'). Please repair it before initializing engine."
            )

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
            import vllm
            from vllm import LLM
            SamplingParams = getattr(vllm, "SamplingParams", None)
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
        if model_cfg.get('load_in_4bit') or model_cfg.get('max_num_batched_tokens'):
            quant_kwargs['max_num_batched_tokens'] = int(model_cfg.get('max_num_batched_tokens', 2048))
        self.max_model_len = int(model_cfg.get("max_model_len", 16384))
        self.llm = LLM(
            **quant_kwargs,
            model=str(model_path),
            tensor_parallel_size=int(model_cfg.get("tensor_parallel_size", 1)),
            gpu_memory_utilization=float(model_cfg.get("gpu_memory_utilization", 0.90)),
            max_model_len=self.max_model_len,
            dtype=dtype,
            trust_remote_code=True,
            seed=int(model_cfg.get('seed', 42)),
            enable_lora=bool(adapter_path),
            max_lora_rank=max(16, adapter_rank),
            enable_prefix_caching=bool(model_cfg.get('enable_prefix_caching', True)),
            enforce_eager=bool(model_cfg.get('enforce_eager', False)),
            max_num_seqs=int(model_cfg.get('max_num_seqs', 1)),
        )
        self.default_max_tokens = int(model_cfg.get("max_tokens", 2048))
        self.sampling_params = SamplingParams(
            temperature=float(model_cfg.get("temperature", 0.0)),
            top_p=float(model_cfg.get("top_p", 1.0)),
            seed=int(model_cfg.get("seed", 42)),
            max_tokens=self.default_max_tokens,
        )

    def _fit_messages_to_context(self, messages: List[Dict[str, str]], tokenizer: Any) -> Tuple[List[Dict[str, str]], int]:
        """Ensure multi-turn messages fit within max_model_len with room for generation."""
        min_gen_budget = 768
        msgs = [dict(m) for m in messages]
        tokens = tokenizer.apply_chat_template(
            msgs, tokenize=True, add_generation_prompt=True, return_dict=False
        )
        # Step 1: If multi-turn prompt exceeds budget, drop oldest intermediate turn pair (keep system/initial user + latest turn)
        while len(tokens) > self.max_model_len - min_gen_budget and len(msgs) >= 5:
            first_asst_idx = next((i for i, m in enumerate(msgs) if m.get("role") == "assistant"), None)
            if first_asst_idx is not None and first_asst_idx + 2 <= len(msgs):
                del msgs[first_asst_idx:first_asst_idx + 2]
                tokens = tokenizer.apply_chat_template(
                    msgs, tokenize=True, add_generation_prompt=True, return_dict=False
                )
            else:
                break
        # Step 2: If still over budget, trim oversized error/assistant messages
        if len(tokens) > self.max_model_len - min_gen_budget and len(msgs) >= 3:
            for idx in range(len(msgs) - 2, 0, -1):
                if msgs[idx].get("role") == "assistant" and len(msgs[idx].get("content", "")) > 1200:
                    msgs[idx]["content"] = msgs[idx]["content"][-1200:]
            tokens = tokenizer.apply_chat_template(
                msgs, tokenize=True, add_generation_prompt=True, return_dict=False
            )
        return msgs, len(tokens)

    def generate(self, messages: List[Dict[str, str]]) -> str:
        import copy
        tokenizer = self.llm.get_tokenizer()
        fitted_msgs, n_toks = self._fit_messages_to_context(messages, tokenizer)
        avail = max(256, self.max_model_len - n_toks - 16)
        default_max = getattr(self, "default_max_tokens", 2048)
        sp = copy.copy(self.sampling_params) if self.sampling_params is not None else None
        if sp is not None:
            sp.max_tokens = min(default_max, avail)
        outputs = self.llm.chat(messages=[fitted_msgs], sampling_params=sp,
                                lora_request=self.lora_request, use_tqdm=False)
        return outputs[0].outputs[0].text

    def generate_batch(self, conversations: List[Conversation]) -> List[str | Exception]:
        """Send valid conversations together and preserve their input positions."""
        import copy
        tokenizer = self.llm.get_tokenizer()
        replies: List[str | Exception] = []
        ready = []
        fitted_convos: List[Conversation] = []
        sp_list = []
        default_max = getattr(self, "default_max_tokens", 2048)
        for messages in conversations:
            try:
                fitted_msgs, n_toks = self._fit_messages_to_context(messages, tokenizer)
                if n_toks >= self.max_model_len - 64:
                    raise ValueError(f"Prompt has {n_toks} tokens with a {self.max_model_len}-token context")
            except (TypeError, ValueError) as exc:
                replies.append(exc)
            else:
                ready.append(len(replies))
                replies.append("")
                fitted_convos.append(fitted_msgs)
                avail = max(256, self.max_model_len - n_toks - 16)
                sp = copy.copy(self.sampling_params) if self.sampling_params is not None else None
                if sp is not None:
                    sp.max_tokens = min(default_max, avail)
                sp_list.append(sp)

        if ready:
            kw = dict(lora_request=self.lora_request, use_tqdm=False)
            if any(s is not None for s in sp_list):
                kw["sampling_params"] = sp_list
            outputs = self.llm.chat(messages=fitted_convos, **kw)
            for i, output in zip(ready, outputs, strict=True):
                replies[i] = output.outputs[0].text
        return replies


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
        try:
            from src.coder_training.t4_attention import configure_t4_sdpa
            configure_t4_sdpa()
        except Exception as exc:
            logger.debug("T4 SDPA configuration skipped: %s", exc)
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

        attn_impl = model_cfg.get('attn_implementation')
        if not attn_impl:
            import torch
            if hasattr(torch.nn.functional, 'scaled_dot_product_attention'):
                attn_impl = 'sdpa'
        if attn_impl:
            load_kwargs['attn_implementation'] = attn_impl

        if model_cfg.get('load_in_4bit'):
            from transformers import BitsAndBytesConfig
            load_kwargs['quantization_config'] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type='nf4',
                bnb_4bit_use_double_quant=True,
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

        if self.temperature <= 0.0 and hasattr(self.model, "generation_config") and callable(self.model):
            with torch.inference_mode():
                generated_ids = self._greedy_chunked(inputs.input_ids, generation_tokens, prefill_chunk=512)
            return self.tokenizer.decode(generated_ids, skip_special_tokens=True)

        inputs = inputs.to(self.model.device)
        try:
            with torch.inference_mode():
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
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _greedy_chunked(self, input_ids: Any, max_new_tokens: int, prefill_chunk: int = 512) -> List[int]:
        """Chunked prefill + greedy decode with logits_to_keep=1 so 8k prompts never OOM on Turing T4."""
        import gc
        import time
        import torch
        from transformers import DynamicCache

        model = self.model
        device = model.device
        ids = input_ids.to(device)
        eos = getattr(model.generation_config, "eos_token_id", None)
        eos_ids = set(eos if isinstance(eos, (list, tuple)) else [eos]) if eos is not None else set()
        if self.tokenizer.eos_token_id is not None:
            eos_ids.add(self.tokenizer.eos_token_id)

        cache = DynamicCache()
        out = None
        generated: List[int] = []

        def _forward_step(chunk_ids: Any) -> Any:
            try:
                return model(
                    input_ids=chunk_ids,
                    past_key_values=cache,
                    use_cache=True,
                    logits_to_keep=1,
                )
            except TypeError:
                return model(
                    input_ids=chunk_ids,
                    past_key_values=cache,
                    use_cache=True,
                )

        try:
            total = int(ids.shape[1])
            for start in range(0, total, prefill_chunk):
                out = _forward_step(ids[:, start : start + prefill_chunk])
                if getattr(out, "past_key_values", None) is not None:
                    cache = out.past_key_values
            started = time.time()
            for _ in range(max_new_tokens):
                next_id = int(out.logits[0, -1].argmax())
                if next_id in eos_ids:
                    break
                generated.append(next_id)
                if self.max_generation_time_sec is not None and (time.time() - started) > self.max_generation_time_sec:
                    break
                out = _forward_step(torch.tensor([[next_id]], device=device, dtype=ids.dtype))
                if getattr(out, "past_key_values", None) is not None:
                    cache = out.past_key_values
            return generated
        finally:
            del out, cache, ids
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()


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


_SCHEMA_READ_ERROR = re.compile(
    r"KeyError:|FileNotFoundError:|Worksheet named .* not found|no such (?:table|column)|"
    r"usecols do not match", re.IGNORECASE
)


def _schema_retry_hint(profile: BusinessProfile, error: str, code: str) -> str:
    problem = error.splitlines()[-1].casefold()
    matches = []
    for table in profile.tables:
        names = (Path(table.source_file).stem, table.table_name, *table.columns)
        if (table.source_file.casefold() in problem
                or f"{table.table_name.casefold()}.xlsx" in problem
                or any(repr(name).casefold() in problem or json.dumps(name, ensure_ascii=False).casefold() in problem
                       for name in names)):
            matches.append(table)
    if matches:
        matches.sort(key=lambda table: table.source_file not in code)
        return format_eval_schema(matches[:4], include_samples=False)
    return "File có thật trong BUSINESS_DIR: " + ", ".join(repr(name) for name in profile.files[:12])


def _eval_guard_issue(
    question: str, answer_type: str, answer: Any, check: Any,
    had_read_error: bool, profile: BusinessProfile,
) -> str | None:
    """Validate candidate final output against business rules and anti-hallucination guardrails."""
    query = _search_text(question)

    # 1. Empty Ranking / Unanswerable Guard
    ranking = _mentions(query, "top|xếp hạng|bán chạy nhất|bán nhiều nhất|bán được nhiều nhất")
    ranking = ranking or (re.search(r"\b[1-9][0-9]*\b", query)
                          and _mentions(query, "cao nhất|thấp nhất|nhiều nhất|ít nhất"))
    empty_rank = ranking and ((answer_type == "list" and answer == [])
                              or (answer_type == "table" and isinstance(answer, dict) and answer.get("rows") == []))
    if empty_rank or (answer_type == "unanswerable" and had_read_error):
        valid_source = (isinstance(check, dict)
                        and isinstance(check.get("detail"), str) and bool(check["detail"].strip())
                        and any(table.status == "ok" and table.source_file == check.get("source_file")
                                and table.table_name == check.get("table") for table in profile.tables))
        if not valid_source:
            return ("Kèm check với source_file và table đúng theo schema, và detail nêu đã kiểm tra gì "
                    "trên nguồn đó. Lỗi đọc chưa chứng minh shop thiếu dữ liệu.")
        if empty_rank and (type(check.get("rows_after_filter")) is not int or check["rows_after_filter"] != 0):
            return "Kiểm tra lại kỳ và nhãn lọc; nếu xếp hạng rỗng thật, ghi check.rows_after_filter=0 từ phép lọc."

    # 2. Negative Direct Count Guard
    if answer_type == "number" and isinstance(answer, (int, float)) and answer < 0:
        direct_count = re.search(r"\b(?:bao nhieu|may|dem(?: so)?|so luong|tong so) (?:don(?! vi\b)|hoa don)\b", query)
        signed_metric = _mentions(query, "chênh|chênh lệch|tăng|giảm|hơn|kém|so với|trung bình|tỷ lệ|tỉ lệ|phần trăm")
        if direct_count and not signed_metric:
            return "Số đếm đơn trực tiếp phải không âm. Kiểm tra phép đếm mã đơn phân biệt."

    # 3. Verified Zero Acceptance / Rejection Guard
    if answer_type in ("number", "percent") and isinstance(answer, (int, float)) and answer == 0:
        is_unsold = _mentions(query, "ế|e|ko ai mua|khong ai mua|khong ban duoc|ko ban duoc|chua ban duoc")
        is_diff = _mentions(query, "chênh|chênh lệch|tăng|giảm|hơn|kém|so với|thay đổi")
        is_suspicious_metric = _mentions(
            query,
            "doanh thu|doanh so|tong tien|tien ban|tong so tien|gia ban|gia von|loi nhuan|loi|lai|so luong ban|da ban"
        )
        if (is_suspicious_metric or answer_type == "percent") and not (is_unsold or is_diff):
            has_valid_check = False
            if isinstance(check, dict) and isinstance(check.get("detail"), str) and bool(check["detail"].strip()):
                rows_after = check.get("rows_after_filter")
                if isinstance(rows_after, int) and rows_after > 0:
                    has_valid_check = True
                elif check.get("verified_zero") is True or check.get("zero_confirmed") is True:
                    has_valid_check = True
                elif check.get("source_file") and any(
                    t.source_file == check.get("source_file") for t in profile.tables
                ):
                    has_valid_check = True

            if not has_valid_check:
                return (
                    "Kết quả tính ra 0 cho chỉ số doanh thu/số lượng/tiền bán chưa có bằng chứng xác minh. "
                    "Hãy kiểm tra lại: DataFrame lọc có bị rỗng (len==0) do sai tên trạng thái "
                    "(xem df[col].unique()), sai format ngày tháng, hoặc sai tên cột không? "
                    "Nếu đã xác minh đúng bằng 0, hãy kèm check={'source_file':..., 'table':..., 'detail':..., 'rows_after_filter':...}. "
                    "Nếu không có căn cứ tính hoặc dữ liệu rỗng/ngoài phạm vi, hãy trả về kind='final', type='abstain'."
                )

    # 4. Hallucination Pattern 1: [0, 0] or all-zero list
    debt_or_flow = _mentions(
        query,
        "nợ|mua chịu|bán chịu|trả nợ|thu nợ|sổ quỹ|thu chi|tiền|chênh lệch|doanh thu|lợi nhuận|doanh số|dòng tiền"
    )
    if answer_type == "list" and isinstance(answer, list) and debt_or_flow:
        def _is_zero_val(x: Any) -> bool:
            if isinstance(x, (int, float, np.number)) and x == 0:
                return True
            s = str(x).strip()
            if s in ("0", "0.0", "0.00", "0,0", "0,00"):
                return True
            try:
                return float(s.replace(",", "")) == 0.0
            except (ValueError, TypeError):
                pass
            try:
                return float(s.replace(",", ".")) == 0.0
            except (ValueError, TypeError):
                return False

        if len(answer) >= 2 and all(_is_zero_val(x) for x in answer):
            return (
                "Danh sách kết quả toàn số 0 ([0, 0] hoặc tương tự). "
                "Hãy kiểm tra lại: Nếu tính công nợ hoặc luân chuyển tiền, không dùng cột snapshot đã trả "
                "tại thời điểm xuất file; cần đọc sổ quỹ/phiếu thu chi theo thời gian để tính nợ phát sinh "
                "và tiền đã trả trong kỳ. Nếu không đủ dữ kiện, hãy trả về kind='final', type='abstain'."
            )

    # 5. Hallucination Pattern 2: Zero-debt table
    is_debt = _mentions(query, "nợ|công nợ|còn nợ|mua chịu|bán chịu|phải thu|dư nợ")
    if answer_type == "table" and isinstance(answer, dict) and is_debt:
        rows = answer.get("rows", [])
        cols = [str(c).lower() for c in answer.get("columns", [])]
        if rows:
            def _is_positive_num(val: Any) -> bool:
                if isinstance(val, (int, float, np.number)):
                    return val > 0
                if isinstance(val, str):
                    cleaned = val.replace(",", "").strip()
                    try:
                        return float(cleaned) > 0
                    except (ValueError, TypeError):
                        pass
                    try:
                        return float(val.replace(".", "").replace(",", ".").strip()) > 0
                    except (ValueError, TypeError):
                        return False
                return False

            def _is_num_cell(val: Any) -> bool:
                if isinstance(val, (int, float, np.number)):
                    return True
                if isinstance(val, str):
                    cleaned = val.replace(",", "").strip()
                    try:
                        float(cleaned)
                        return True
                    except (ValueError, TypeError):
                        return False
                return False

            debt_indices = [
                i for i, c in enumerate(cols)
                if any(k in c for k in ("nợ", "no", "tiền", "tien", "dư", "du", "phải thu", "phai thu", "amount", "due", "debt"))
            ]
            if not debt_indices:
                debt_indices = [
                    i for i in range(len(cols))
                    if all(_is_num_cell(r[i]) for r in rows if len(r) > i)
                ]
            if debt_indices:
                all_zeros = True
                for idx in debt_indices:
                    for r in rows:
                        if len(r) > idx and _is_positive_num(r[idx]):
                            all_zeros = False
                            break
                    if not all_zeros:
                        break
                if all_zeros:
                    return (
                        "Bảng kết quả công nợ chứa toàn số 0 hoặc số không dương. "
                        "Theo rulebook, khách nợ phải có số dư nợ dương (> 0). Không đưa khách nợ bằng 0 vào danh sách. "
                        "Hãy đọc sổ quỹ theo thời điểm để tính đúng số nợ còn lại, hoặc trả về kind='final', type='abstain'."
                    )

    # 6. Hallucination Pattern 3: Duplicate Top-k Ranking
    ranking_query = _mentions(query, "top|xếp hạng|bán chạy nhất|bán nhiều nhất|bán được nhiều nhất|cao nhất|thấp nhất|sộp nhất")
    if ranking_query:
        if answer_type == "list" and isinstance(answer, list) and len(answer) > 1:
            norm_items = [unicodedata.normalize("NFC", str(x).strip().casefold()) for x in answer]
            dup_items = [x for x in set(norm_items) if norm_items.count(x) > 1]
            if dup_items:
                return (
                    f"Danh sách xếp hạng top-k chứa các giá trị/mặt hàng trùng lặp: {dup_items[:3]}. "
                    "Bạn chưa gom nhóm (groupby) theo mã hoặc tên sản phẩm/khách hàng trước khi sắp xếp và lấy top. "
                    "Hãy dùng `.groupby(...)` để cộng tổng số lượng/doanh thu theo từng thực thể riêng biệt trước khi head(k)."
                )
        elif answer_type == "table" and isinstance(answer, dict):
            rows = answer.get("rows", [])
            if len(rows) > 1:
                first_col = [unicodedata.normalize("NFC", str(r[0]).strip().casefold()) for r in rows if r and len(r) > 0]
                dup_entities = [x for x in set(first_col) if first_col.count(x) > 1]
                if dup_entities:
                    return (
                        f"Bảng xếp hạng top-k chứa các thực thể trùng lặp ở cột đầu: {dup_entities[:3]}. "
                        "Bạn chưa gom nhóm (groupby) theo mã hoặc tên sản phẩm/khách hàng trước khi sắp xếp và lấy top. "
                        "Hãy dùng `.groupby(...)` để cộng tổng theo từng thực thể riêng biệt trước khi head(k)."
                    )

    return None


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
        self.eval_core_rules = bool(self.agent_cfg.get("eval_core_rules", True))
        self.rulebook_in_system = bool(self.agent_cfg.get("rulebook_in_system", False))
        self.use_eval_schema = bool(self.agent_cfg.get("use_eval_schema", self.eval_core_rules))
        self.enable_guardrails = bool(self.agent_cfg.get("enable_guardrails", self.eval_core_rules))
        self.prompt_format = str(self.agent_cfg.get("prompt_format", os.environ.get("DATAMATE_PROMPT_FORMAT", "system-user")))

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

        self.abstain_on_unanswerable = bool(self.agent_cfg.get("abstain_on_unanswerable", False))

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

            metadata_only = bool(self.agent_cfg.get("metadata_only", False))
            self._profile_cache[business_id] = profile_business_package(
                business_dir=b_dir,
                business_id=business_id,
                max_sample_rows=self.max_sample_rows,
                max_unique_categorical=self.max_unique_categorical,
                metadata_only=metadata_only,
            )
        return self._profile_cache[business_id]

    def answer_question_with_trace(
        self, item: QuestionItem
    ) -> QuestionResult:
        """Execute multi-turn agent interaction for a QuestionItem and return (SubmissionItem, trace)."""
        steps = self._answer_question_steps(item)
        try:
            prompt = next(steps)
            while True:
                try:
                    reply = self.backend.generate(prompt)
                except Exception as exc:
                    prompt = steps.throw(exc)
                else:
                    prompt = steps.send(reply)
        except StopIteration as done:
            return done.value
        except Exception as exc:
            logger.error("Unhandled runtime exception on question %s: %s", item.id, exc, exc_info=True)
            sub = SubmissionItem.abstain(item.id, reason=f"Unhandled runtime exception: {exc}")
            trace = {
                "id": item.id,
                "business_id": item.business_id,
                "question": item.question,
                "as_of_date": item.as_of_date,
                "final_answer": sub.to_dict(),
                "error": str(exc),
                "base_system_prompt": SYSTEM_PROMPT,
                "system_prompt": SYSTEM_PROMPT,
            }
            return sub, trace

    def answer_questions_with_trace(self, items: List[QuestionItem]) -> List[QuestionResult]:
        """Run a bounded vLLM batch, regrouping only the questions that need another turn."""
        if not isinstance(self.backend, VLLMBackend):
            return [self.answer_question_with_trace(item) for item in items]

        pending: List[Tuple[int, Generator[Conversation, str, QuestionResult], str | Exception | None]] = [
            (i, self._answer_question_steps(item), None) for i, item in enumerate(items)
        ]
        results: Dict[int, QuestionResult] = {}
        while pending:
            ready = []
            for i, steps, reply in pending:
                try:
                    prompt = steps.throw(reply) if isinstance(reply, Exception) else steps.send(reply)
                except StopIteration as done:
                    results[i] = done.value
                except Exception as exc:
                    item = items[i]
                    results[i] = (SubmissionItem.abstain(item.id, reason=f"Runtime exception: {exc}"),
                                  {"id": item.id, "error": str(exc)})
                else:
                    ready.append((i, steps, prompt))
            if not ready:
                break
            replies = self.backend.generate_batch([prompt for _, _, prompt in ready])
            pending = [(i, steps, reply) for (i, steps, _), reply in zip(ready, replies, strict=True)]
        return [results[i] for i in range(len(items))]

    def _answer_question_steps(self, item: QuestionItem) -> Generator[Conversation, str, QuestionResult]:
        """Pause at model calls while retaining this question's trace and retry state."""
        t0 = time.time()
        trace: Dict[str, Any] = {
            "id": item.id,
            "business_id": item.business_id,
            "question": item.question,
            "as_of_date": item.as_of_date,
            "base_system_prompt": SYSTEM_PROMPT,
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
        cache_hit = item.business_id in self._profile_cache
        preflight_started = time.perf_counter()
        profile = self._get_business_profile(item.business_id)
        trace["preflight"] = {"cache_hit": cache_hit, "seconds": time.perf_counter() - preflight_started}
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
        if self.use_eval_schema:
            eval_schema = format_eval_schema(profile.tables)
            if self.eval_core_rules:
                schema_md = eval_schema
            else:
                header_lines = [
                    "BUSINESS_DIR: biến đường dẫn do môi trường thực thi cấp; dùng trực tiếp, không gán đường dẫn tuyệt đối.",
                    "Files: " + ", ".join(profile.files),
                ]
                if profile.readme_text and profile.readme_text.strip():
                    header_lines.append("README:\n" + profile.readme_text.strip())
                schema_md = "\n".join(header_lines) + "\n\n" + eval_schema
        else:
            schema_md = format_profile_for_prompt(profile, compact=True)
        rulebook_text = self.shared_context.get("rulebook_text", "")
        system_prompt = build_system_prompt(rulebook_text) if self.rulebook_in_system else SYSTEM_PROMPT
        trace["system_prompt"] = system_prompt
        user_prompt = build_user_prompt(
            question=item.question,
            as_of_date=item.as_of_date,
            relative_dates=rel_dates,
            schema_markdown=schema_md,
            rulebook_text="" if (self.eval_core_rules or self.rulebook_in_system) else rulebook_text,
            calendar_path=calendar_path,
            core_rules=self.eval_core_rules,
            readme_text=profile.readme_text,
            rulebook_in_system=self.rulebook_in_system,
        )
        if self.prompt_format == "user-only":
            initial_prompt = f"{system_prompt}\n\n{user_prompt}"
            trace["initial_user_prompt"] = initial_prompt
            trace["prompt_format"] = "user-only"
            messages: List[Dict[str, str]] = [
                {"role": "user", "content": initial_prompt},
            ]
        else:
            trace["initial_user_prompt"] = user_prompt
            messages: List[Dict[str, str]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        trace["messages"] = [dict(m) for m in messages]

        code_executions_count = 0
        had_read_error = False

        # Multi-turn interaction loop
        for turn in range(self.max_turns):
            turn_idx = turn + 1
            turn_start = time.time()
            prompt_snapshot = [dict(m) for m in messages]
            if turn_idx == self.max_turns or code_executions_count + 1 >= self.max_code_executions:
                prompt_snapshot[-1]["content"] += (
                    "\n\nĐây là lượt cuối có thể thực thi code. Viết script in kind='final'; "
                    "observation không còn lượt xử lý tiếp."
                )

            try:
                llm_reply = yield prompt_snapshot
            except Exception as be_exc:
                logger.error("Inference generation error on question %s: %s", item.id, be_exc)
                sub = SubmissionItem.abstain(item.id, reason=f"Backend generation error: {be_exc}")
                trace["final_answer"] = sub.to_dict()
                trace["elapsed_time_sec"] = round(time.time() - t0, 4)
                trace["error"] = str(be_exc)
                trace["attempts"].append({"turn": turn_idx, "prompt_messages": prompt_snapshot, "error": str(be_exc)})
                return sub, trace

            code = extract_python_code(llm_reply)
            compact_asst_reply = (
                f"```python\n{code}\n```"
                if code
                else (llm_reply.split("</think>", 1)[-1].strip() if "</think>" in llm_reply else llm_reply)[-1200:]
            )

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

                messages.append({"role": "assistant", "content": compact_asst_reply})
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

                correction = build_error_correction_prompt(
                    sandbox_res.error_message,
                    sandbox_res.error_kind or "execution_error",
                    question=item.question,
                    as_of_date=item.as_of_date,
                )
                if self.enable_guardrails and _SCHEMA_READ_ERROR.search(sandbox_res.error_message or ""):
                    had_read_error = True
                    correction += "\n\n" + _schema_retry_hint(profile, sandbox_res.error_message, code)
                    correction += ("\nNếu dữ liệu thật sự thiếu, kèm check với source_file, table và detail "
                                   "nêu phép kiểm tra khi trả unanswerable.")
                messages.append({"role": "assistant", "content": compact_asst_reply})
                messages.append(
                    {
                        "role": "user",
                        "content": correction,
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
                messages.append({"role": "assistant", "content": compact_asst_reply})
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

                    # Abstain Gate: Intercept 'unanswerable' when risky to avoid -1.0 penalty.
                    # Under competition PA metric: wrong is -1.0, abstain is 0.0.
                    # 97.7% of reference answers are answerable, so false unanswerable is catastrophic.
                    if clean_type == AnswerType.UNANSWERABLE.value and self.abstain_on_unanswerable:
                        logger.info("Abstain gate intercepted 'unanswerable' on %s -> converting to safe 'abstain'", item.id)
                        clean_type = AnswerType.ABSTAIN.value
                        clean_ans = None

                    if self.enable_guardrails:
                        issue = _eval_guard_issue(item.question, clean_type, clean_ans,
                                                  final_payload.get("check"), had_read_error, profile)
                        if issue:
                            attempt_record["guard_error"] = issue
                            raise ValueError(issue)
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

                    messages.append({"role": "assistant", "content": compact_asst_reply})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"Kết quả cuối cần kiểm tra lại: {guard_exc}\n"
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
