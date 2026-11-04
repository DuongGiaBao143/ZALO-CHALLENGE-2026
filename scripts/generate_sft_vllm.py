"""Zalo AI Challenge 2026 — DataMate
Execution-filtered SFT generation using vLLM batches and bounded CPU workers.
Runs as a clean standalone script to bypass Colab IPython kernel IPC multiprocessing issues.
"""

import os
import sys
import time
import json
import shutil
import argparse
import ast
import concurrent.futures
import tempfile
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from tqdm import tqdm

# Ensure project root is in python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Safe environment settings & Enforce Online Mode for HuggingFace Hub downloads
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"
os.environ["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

from src.profiler.business_loader import profile_business_package, format_profile_for_prompt
from src.time_resolver.calendar_utils import resolve_relative_dates
from src.agent.prompts import build_user_prompt, build_observation_prompt, build_error_correction_prompt, SYSTEM_PROMPT
from src.agent.sandbox import SandboxResult, extract_python_code, run_python_in_sandbox
from src.eval.scorer import score_single_answer
from src.coder_training.io_utils import writable_output
from src.coder_training.collector import is_safe_code


QUESTION_CODE_SYSTEM_PROMPT = """Viết một chương trình Python hoàn chỉnh để trả lời câu hỏi bên dưới.
Chỉ xuất một khối ```python ... ```; không trả lời bằng số hay văn xuôi.
Khi chạy, chương trình được cung cấp BUSINESS_DIR (thư mục shop, chỉ đọc), AS_OF_DATE
(ngày tham chiếu YYYY-MM-DD), RULEBOOK_PATH và CALENDAR_PATH. Có pandas, numpy,
sqlite3, os, json, parse_vn_number, parse_vn_date, vn_norm; Excel mặc định dùng Calamine.
Chương trình phải tự liệt kê file, khám phá sheet/bảng/cột và kiểm tra các giá trị thực tế
trước khi tính toán; không giả định shop nào, tên file, tên cột hay cách ghi trạng thái.
Tự đọc README của shop và rulebook nếu có để áp dụng quy tắc. SQLite mở mode=ro.
Dùng AS_OF_DATE cho hôm nay/tháng này; không dùng ngày máy tính hoặc gán ngày cố định.
Không ghi vào BUSINESS_DIR, không đọc questions.jsonl/answers.jsonl, không gọi mạng/LLM.
Mọi bước khám phá và tính toán phải nằm trong cùng chương trình; không in observation
để yêu cầu một lượt model tiếp theo. Nếu không xác định chắc chắn, trả abstain.
In JSON ở dòng cuối: {"kind":"final","type":"number|percent|string|date|boolean|list|table|unanswerable|abstain",
"answer": giá_trị_hoặc_null, "evidence":"dẫn chứng ngắn", "reason":"lý do nếu thiếu dữ liệu"}.
Chỉ dùng unanswerable khi đã kiểm tra dữ liệu và xác định thiếu căn cứ thực sự.
"""


def is_valid_solution_code(code: str) -> bool:
    """Kiểm tra chống ăn may / gán cứng kết quả (Anti-Shortcut Filter)."""
    if not code or len(code.strip()) < 30:
        return False
    has_data_read = any(term in code for term in ["read_csv", "read_excel", "sqlite3", "duckdb", "open("])
    if not has_data_read:
        return False
    if "print(" not in code:
        return False
    return True


def sanitize_solution_code(code: str) -> str:
    """Xóa bỏ các dòng gán cứng đường dẫn môi trường (BUSINESS_DIR, CALENDAR_PATH) do LLM copy từ prompt."""
    import re
    cleaned = re.sub(r'^\s*(BUSINESS_DIR|CALENDAR_PATH)\s*=\s*["\'/].*$\n?', '', code, flags=re.MULTILINE)
    return cleaned.strip()


def evaluate_generation(output, item, calendar_path, work_root, timeout_sec,
                        rulebook_path, question_only):
    completion = output.outputs[0] if output.outputs else None
    reply = completion.text.strip() if completion else ""
    code = extract_python_code(reply)
    clean_code = sanitize_solution_code(code) if code else None
    started = time.perf_counter()
    result = SandboxResult(
        success=False, error_kind="code_filter" if code else "no_python_code",
        error_message="Code must contain a Python block, read business data, and print JSON.",
    )
    valid = bool(code and is_valid_solution_code(code))
    if valid and question_only:
        valid, reason = is_safe_code(clean_code, item["qid"])
        if valid:
            # shortcut: discovery calls are a structural check, not proof of generalization.
            discovery_calls = {"listdir", "scandir", "walk", "glob", "rglob", "iterdir"}
            valid = any(isinstance(node, ast.Call) and
                        ((isinstance(node.func, ast.Attribute) and node.func.attr in discovery_calls) or
                         (isinstance(node.func, ast.Name) and node.func.id in discovery_calls))
                        for node in ast.walk(ast.parse(clean_code)))
            reason = "Program must discover business files at runtime, not assume a known filename"
        if not valid:
            result.error_message = reason
    if valid:
        try:
            with tempfile.TemporaryDirectory(dir=work_root) as worker_dir:
                result = run_python_in_sandbox(
                    code=clean_code, business_dir=item["biz_dir"], calendar_path=calendar_path,
                    work_dir=worker_dir, timeout_sec=timeout_sec,
                    as_of_date=item["as_of_date"], rulebook_path=rulebook_path,
                )
        except Exception as exc:
            result = SandboxResult(success=False, error_kind="worker_error", error_message=str(exc))
    attempt = asdict(result)
    attempt.update(
        llm_reply=reply, generated_code=clean_code,
        finish_reason=getattr(completion, "finish_reason", None),
        sandbox_sec=round(time.perf_counter() - started, 4),
    )
    return attempt


def main():
    parser = argparse.ArgumentParser(description="DataMate SFT Generator via vLLM")
    parser.add_argument("--model-id", default="Qwen/Qwen2.5-Coder-14B-Instruct", help="Hugging Face model ID or local model path")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "result" / "sft_folder_schema_v1", help="Dataset and generation log directory")
    parser.add_argument("--drive-backup-dir", type=Path, default=Path("/content/drive/MyDrive/datamate_sft_backup"), help="Backup directory under an existing Drive mount")
    parser.add_argument("--batch-size", type=int, default=16, help="Batch size for vLLM generation")
    parser.add_argument("--max-samples", type=int, default=None, help="Max samples to generate (None for all)")
    parser.add_argument("--gpu-util", type=float, default=0.88, help="GPU memory utilization")
    parser.add_argument("--max-model-len", type=int, default=16384, help="Max model context length (default: 16384)")
    parser.add_argument("--max-tokens", type=int, default=650, help="Max output tokens")
    parser.add_argument("--sandbox-workers", type=int, default=2, help="Concurrent CPU sandbox processes")
    parser.add_argument("--sandbox-timeout", type=int, default=35, help="Per-execution timeout in seconds")
    parser.add_argument("--question-only", action="store_true", help="Generate one self-discovering program from the original question; save question/code pairs")
    parser.add_argument("--lora-adapter", type=str, default=None, help="Path to LoRA adapter weights (e.g. result/sft_adapter_qwen7b/final_adapter)")
    parser.add_argument("--tensor-parallel-size", "--tp", type=int, default=1, help="Tensor parallel size (e.g. 2 for Kaggle T4x2)")
    parser.add_argument("--dtype", default="auto", choices=["auto", "bfloat16", "float16"], help="Data type for vLLM (use float16 on T4, bfloat16 on A100)")
    parser.add_argument("--max-lora-rank", type=int, default=64, help="Max LoRA rank for vLLM (default: 64)")
    parser.add_argument("--backend", default="auto", choices=["auto", "vllm", "transformers"], help="Inference backend: 'vllm', 'transformers', or 'auto'")
    args = parser.parse_args()
    if min(args.batch_size, args.sandbox_workers, args.sandbox_timeout, args.max_tokens) < 1:
        parser.error("Batch size, sandbox workers, sandbox timeout and max tokens must be positive")
    if args.max_model_len <= args.max_tokens + 16:
        parser.error("max-model-len must exceed max-tokens + 16")
    if args.max_samples is not None and args.max_samples < 1:
        parser.error("max-samples must be positive")
    import pandas as pd
    try:
        import python_calamine  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("Install python-calamine in this runtime before generating SFT") from exc
    pd.set_option("io.excel.xlsx.reader", "calamine")
    sandbox_workers = min(args.sandbox_workers, args.batch_size, os.cpu_count() or 1)
    work_root = writable_output(PROJECT_ROOT / "tmp" / "sandbox_work")
    work_root.mkdir(parents=True, exist_ok=True)
    print(f"SFT runtime: {Path(__file__).resolve()} | Model: {args.model_id} | Mode: {'question_only' if args.question_only else 'folder_readme_schema_v1'}", flush=True)
    print(f"Excel engine: calamine {version('python-calamine')} | pandas {pd.__version__} | Sandbox workers: {sandbox_workers} | Timeout: {args.sandbox_timeout}s", flush=True)

    # Thư mục dữ liệu
    DATA_DIR = PROJECT_ROOT / "data" / "train"
    QUESTIONS_FILE = DATA_DIR / "questions.jsonl"
    ANSWERS_FILE = DATA_DIR / "answers.jsonl"
    CALENDAR_FILE = DATA_DIR / "calendar.csv"
    RULEBOOK_FILE = DATA_DIR / "rulebook.md"

    MODEL_ID = args.model_id
    OUTPUT_DIR = writable_output(args.output_dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_SFT_FILE = OUTPUT_DIR / ("verified_question_code_dataset.jsonl" if args.question_only else "verified_sft_dataset.jsonl")
    LOG_FILE = OUTPUT_DIR / ("question_code_generation_log.jsonl" if args.question_only else "generation_log.jsonl")
    if args.question_only:
        contract_path = OUTPUT_DIR / "question_code_contract.json"
        contract = {
            "model_id": MODEL_ID, "input_field": "question", "target_field": "code",
            "system_instruction": QUESTION_CODE_SYSTEM_PROMPT,
            "runtime_inputs": ["BUSINESS_DIR", "AS_OF_DATE", "RULEBOOK_PATH", "CALENDAR_PATH"],
            "model_receives_shop_schema": False, "model_turns": 1,
            "verification": "Final execution output matches train gold; generalization is not certified",
        }
        if contract_path.exists() and json.loads(contract_path.read_text(encoding="utf-8")) != contract:
            raise ValueError("Question/code contract changed; choose a new output directory")
        contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Backup Drive nếu có
    drive_backup = writable_output(args.drive_backup_dir)
    DRIVE_BACKUP_DIR = drive_backup if drive_backup.parent.exists() else None
    if DRIVE_BACKUP_DIR:
        DRIVE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        print(f"☁️ Google Drive Backup: {DRIVE_BACKUP_DIR}")

    # Optional WandB
    use_wandb = False
    try:
        import wandb
        if os.environ.get("WANDB_API_KEY"):
            wandb.login(key=os.environ.get("WANDB_API_KEY"))
            wandb.init(
                project="datamate-sft-data-generation",
                name=f"{Path(MODEL_ID).name}-vllm-batched",
                config={"model_id": MODEL_ID, "batch_size": args.batch_size, "gpu_util": args.gpu_util,
                        "input_mode": "question_only" if args.question_only else "context_messages"}
            )
            use_wandb = True
            print("✅ Weights & Biases logging initialized.")
    except Exception as e:
        print(f"ℹ️ W&B not enabled: {e}")

    # 1. Khởi tạo Engine (vLLM hoặc Transformers)
    backend_to_use = args.backend
    llm = None
    model_obj = None
    tokenizer = None

    lora_path = None
    if args.lora_adapter:
        candidate_lora = Path(args.lora_adapter).resolve()
        if (candidate_lora / "final_adapter" / "adapter_config.json").exists():
            lora_path = candidate_lora / "final_adapter"
        elif (candidate_lora / "adapter_config.json").exists():
            lora_path = candidate_lora
        elif candidate_lora.exists():
            lora_path = candidate_lora
        else:
            raise FileNotFoundError(f"Không tìm thấy adapter LoRA tại: {candidate_lora}")
        print(f"🎯 Đã tìm thấy LoRA Adapter: {lora_path}")

    if backend_to_use in ("auto", "vllm"):
        try:
            print(f"🚀 Thử khởi tạo vLLM Engine ({MODEL_ID}) với TP = {args.tensor_parallel_size}, dtype = {args.dtype}...")
            from vllm import LLM, SamplingParams
            from transformers import AutoTokenizer

            os.environ["HF_HUB_OFFLINE"] = "0"
            os.environ["TRANSFORMERS_OFFLINE"] = "0"
            tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True, local_files_only=False)

            llm = LLM(
                model=MODEL_ID,
                tensor_parallel_size=args.tensor_parallel_size,
                gpu_memory_utilization=args.gpu_util,
                max_model_len=args.max_model_len,
                enforce_eager=True,
                trust_remote_code=True,
                dtype=args.dtype,
                seed=42,
                enable_lora=bool(lora_path),
                max_lora_rank=args.max_lora_rank if lora_path else 16,
            )
            sampling_params = SamplingParams(
                temperature=0.0,
                max_tokens=args.max_tokens,
            )
            backend_to_use = "vllm"
            print("✅ vLLM Engine đã sẵn sàng!")
        except Exception as exc:
            if args.backend == "vllm":
                raise
            print(f"ℹ️ vLLM không khả dụng trên môi trường này ({exc}).")
            print("🔄 Tự động chuyển sang backend Transformers + PEFT (device_map='auto')...")
            backend_to_use = "transformers"

    if backend_to_use == "transformers":
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        # Vô hiệu hóa torchao trong peft nếu phiên bản torchao trên môi trường (Kaggle/Colab) bị xung đột (< 0.16.0)
        try:
            import peft.import_utils
            peft.import_utils.is_torchao_available = lambda: False
        except Exception:
            pass
        try:
            import peft.tuners.lora.torchao as peft_torchao
            peft_torchao.is_torchao_available = lambda: False
        except Exception:
            pass

        from peft import PeftModel

        print(f"🚀 Đang khởi tạo Transformers + PEFT Engine ({MODEL_ID}) với device_map='auto'...")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
        tokenizer.padding_side = "left"
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token_id = tokenizer.eos_token_id

        dtype_map = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
            "auto": torch.float16,
        }
        torch_dtype = dtype_map.get(args.dtype, torch.float16)

        n_gpus = torch.cuda.device_count() if torch.cuda.is_available() else 0
        max_mem_dict = None
        if n_gpus > 1:
            # Phân bổ đều trọng số giữa các GPU: GPU 0 giữ tối đa 7GB, GPU 1 giữ tối đa 14GB
            # Giữ lại hơn 7.5GB trống trên mỗi GPU để phục vụ prefill/activation mà không bao giờ OOM!
            max_mem_dict = {0: "7.0GiB", 1: "14.0GiB"}
            print(f"⚖️ Phân bổ bộ nhớ đa GPU: {max_mem_dict}")

        base_model_obj = AutoModelForCausalLM.from_pretrained(
            MODEL_ID,
            torch_dtype=torch_dtype,
            device_map="auto",
            max_memory=max_mem_dict,
            attn_implementation="sdpa",
            trust_remote_code=True,
        )
        if lora_path:
            print(f"🎯 Đang nạp LoRA Adapter vào Transformers: {lora_path}")
            model_obj = PeftModel.from_pretrained(base_model_obj, str(lora_path))
        else:
            model_obj = base_model_obj
        model_obj.eval()
        print("✅ Transformers Engine đã sẵn sàng trên GPU (device_map='auto')!")

    # 2. Đọc câu hỏi và đáp án
    print("Đang nạp câu hỏi và đáp án...")
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        questions = [json.loads(line) for line in f]

    with open(ANSWERS_FILE, "r", encoding="utf-8") as f:
        gold_answers = {item["id"]: item for item in (json.loads(line) for line in f)}

    rulebook_content = RULEBOOK_FILE.read_text(encoding="utf-8") if RULEBOOK_FILE.exists() else ""
    calendar_path_str = str(CALENDAR_FILE) if CALENDAR_FILE.exists() else ""

    # 3. Kiểm tra các câu đã hoàn thành trước đó (Resume)
    processed_ids = set()
    if OUTPUT_SFT_FILE.exists():
        with open(OUTPUT_SFT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if "id" in record:
                        processed_ids.add(record["id"])
                except Exception:
                    pass
    print(f"Tổng số câu hỏi: {len(questions)} | Đã có sẵn: {len(processed_ids)} câu")

    # 4. Pre-cache toàn bộ 30 Shop Schema một lần duy nhất tại startup
    print("Đang xác định thư mục shop..." if args.question_only else "Đang lập chỉ mục schema...")
    biz_cache = {}
    for b_dir in sorted((DATA_DIR / "data").iterdir()):
        if b_dir.is_dir():
            biz_id = b_dir.name
            if args.question_only:
                biz_cache[biz_id] = {"dir": str(b_dir)}
                continue
            prof = profile_business_package(b_dir, business_id=biz_id, max_sample_rows=0, max_unique_categorical=0)
            biz_cache[biz_id] = {
                "profile": prof,
                "schema_markdown": format_profile_for_prompt(prof, compact=True),
                "dir": str(b_dir)
            }
    print(f"Đã xác định {len(biz_cache)} shop; schema không gửi cho model." if args.question_only
          else f"Đã cache {len(biz_cache)} doanh nghiệp vào RAM.")

    target_questions = questions if args.max_samples is None else questions[:args.max_samples]
    remaining_questions = [q for q in target_questions if q["id"] not in processed_ids]
    print(f"🎯 Số câu cần xử lý tiếp theo: {len(remaining_questions)} câu")

    accepted_count = len(processed_ids)
    rejected_count = 0
    unanswerable_count = 0

    sft_out = open(OUTPUT_SFT_FILE, "a", encoding="utf-8")
    log_out = open(LOG_FILE, "a", encoding="utf-8")

    pbar = tqdm(total=len(remaining_questions), desc="vLLM Batched SFT")
    max_allowed_prompt_len = args.max_model_len - args.max_tokens - 16

    def run_turn(items, turn):
        ready = []
        prompts = []
        for item in items:
            prompt = tokenizer.apply_chat_template(item["messages"], tokenize=False, add_generation_prompt=True)
            prompt_tokens = len(tokenizer.encode(prompt))
            if prompt_tokens > max_allowed_prompt_len:
                attempt = asdict(SandboxResult(
                    success=False, error_kind="context_overflow",
                    error_message=f"Prompt {prompt_tokens} tokens exceeds budget {max_allowed_prompt_len}; skipped without truncation",
                ))
                attempt.update(turn=turn, prompt_tokens=prompt_tokens, llm_reply="",
                               generated_code=None, finish_reason=None, sandbox_sec=0.0)
                item["attempts"].append(attempt)
                continue
            ready.append((item, prompt_tokens))
            prompts.append(prompt)
        if not ready:
            return 0.0, 0.0

        class DummyOutput:
            def __init__(self, text, finish_reason="stop"):
                self.outputs = [type("Gen", (), {"text": text, "finish_reason": finish_reason})()]

        pbar.set_postfix(stage=f"LLM turn {turn}", kept=accepted_count)
        started = time.perf_counter()
        if backend_to_use == "vllm":
            if lora_path:
                from vllm.lora.request import LoRARequest
                lora_req = LoRARequest("datamate_sft_lora", 1, str(lora_path))
                outputs = llm.generate(prompts, sampling_params, lora_request=lora_req, use_tqdm=False)
            else:
                outputs = llm.generate(prompts, sampling_params, use_tqdm=False)
        else:
            import torch
            outputs = []
            # Sinh tuần tự từng prompt (bs=1) để triệt tiêu hoàn toàn rủi ro OOM activation trên GPU T4
            dev = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
            for prompt_text in prompts:
                inputs = tokenizer(prompt_text, return_tensors="pt", truncation=True,
                                   max_length=max_allowed_prompt_len).to(dev)
                with torch.inference_mode():
                    gen_ids = model_obj.generate(
                        **inputs,
                        max_new_tokens=args.max_tokens,
                        do_sample=False,
                        pad_token_id=tokenizer.pad_token_id,
                        eos_token_id=tokenizer.eos_token_id,
                    )
                gen_tokens = gen_ids[0][inputs.input_ids.shape[1]:]
                text = tokenizer.decode(gen_tokens, skip_special_tokens=True)
                outputs.append(DummyOutput(text))
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

        generation_sec = time.perf_counter() - started
        if len(outputs) != len(ready):
            raise RuntimeError(f"Engine ({backend_to_use}) returned a different number of outputs ({len(outputs)}) than prompts ({len(ready)})")
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=sandbox_workers) as executor:
            futures = {
                executor.submit(evaluate_generation, out, item, calendar_path_str,
                                work_root, args.sandbox_timeout, str(RULEBOOK_FILE),
                                args.question_only): (item, prompt_tokens)
                for (item, prompt_tokens), out in zip(ready, outputs)
            }
            for done, future in enumerate(concurrent.futures.as_completed(futures), 1):
                item, prompt_tokens = futures[future]
                attempt = future.result()
                attempt.update(turn=turn, prompt_tokens=prompt_tokens)
                item["attempts"].append(attempt)
                pbar.set_postfix(stage=f"sandbox {turn}: {done}/{len(ready)}", kept=accepted_count)
        return generation_sec, time.perf_counter() - started

    for i in range(0, len(remaining_questions), args.batch_size):
        batch_started = time.perf_counter()
        batch_q = remaining_questions[i:i + args.batch_size]
        batch_metadata = []
        for q_item in batch_q:
            biz_info = biz_cache[q_item["business_id"]]
            user_prompt = q_item["question"] if args.question_only else build_user_prompt(
                question=q_item["question"], as_of_date=q_item["as_of_date"],
                relative_dates=resolve_relative_dates(q_item["as_of_date"]),
                schema_markdown=biz_info["schema_markdown"], rulebook_text=rulebook_content,
                calendar_path=calendar_path_str,
            )
            batch_metadata.append({
                "qid": q_item["id"], "biz_id": q_item["business_id"],
                "gold_item": gold_answers[q_item["id"]], "biz_dir": biz_info["dir"],
                "question": q_item["question"], "as_of_date": q_item["as_of_date"],
                "messages": [
                    {"role": "system", "content": QUESTION_CODE_SYSTEM_PROMPT if args.question_only else SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "attempts": [],
            })

        gen_time, sandbox_wall = run_turn(batch_metadata, 1)
        turn2_items = []
        for item in batch_metadata:
            attempt = item["attempts"][-1]
            if args.question_only:
                continue
            # Gold answers only filter completed traces; never decide whether to retry.
            if attempt["success"] and attempt["kind"] == "final":
                continue
            if attempt["error_kind"] == "context_overflow":
                continue
            if attempt["success"] and attempt["kind"] == "observation":
                payload = attempt["parsed_output"]
                follow_up = build_observation_prompt(payload.get("data"), payload.get("message", ""),
                                                     item["question"], item["as_of_date"])
            else:
                follow_up = build_error_correction_prompt(attempt["error_message"], attempt["error_kind"],
                                                         item["question"], item["as_of_date"])
            item["messages"] += [
                {"role": "assistant", "content": attempt["llm_reply"]},
                {"role": "user", "content": follow_up},
            ]
            turn2_items.append(item)

        gen_t2, sandbox_t2 = run_turn(turn2_items, 2)
        gen_time += gen_t2
        sandbox_wall += sandbox_t2
        batch_accepted = 0
        for item in batch_metadata:
            attempt = item["attempts"][-1]
            pred_payload = (attempt["parsed_output"]
                            if attempt["success"] and attempt["kind"] == "final" else None)
            verdict, score = score_single_answer(pred_payload, item["gold_item"])
            messages = item["messages"] + [
                {"role": "assistant", "content": sanitize_solution_code(attempt["llm_reply"])},
            ]
            if verdict == "correct":
                accepted_count += 1
                batch_accepted += 1
                if item["gold_item"].get("type") == "unanswerable":
                    unanswerable_count += 1
                if args.question_only:
                    sft_sample = {
                        "id": item["qid"], "business_id": item["biz_id"],
                        "question": item["question"], "as_of_date": item["as_of_date"],
                        "code": attempt["generated_code"],
                    }
                else:
                    sft_sample = {"id": item["qid"], "business_id": item["biz_id"],
                                  "prompt_format": "folder_readme_schema_v1", "messages": messages}
                sft_out.write(json.dumps(sft_sample, ensure_ascii=False) + "\n")
                sft_out.flush()
            else:
                rejected_count += 1
            log_record = {
                "id": item["qid"], "business_id": item["biz_id"], "model_id": MODEL_ID,
                "lora_adapter": str(lora_path) if lora_path else None,
                "verdict": verdict, "gold": item["gold_item"], "pred": pred_payload,
                "has_code": bool(attempt["generated_code"]), "messages": messages,
                "input_mode": "question_only" if args.question_only else "context_messages",
                "prompt_format": "question_only" if args.question_only else "folder_readme_schema_v1",
                "attempts": item["attempts"], "sandbox_timeout_sec": args.sandbox_timeout,
                "sandbox_workers": sandbox_workers,
                "sandbox_sec": round(sum(a["sandbox_sec"] for a in item["attempts"]), 4),
            }
            log_out.write(json.dumps(log_record, ensure_ascii=False) + "\n")
            log_out.flush()
            pbar.update(1)

        if DRIVE_BACKUP_DIR and OUTPUT_SFT_FILE.exists():
            try:
                shutil.copy2(OUTPUT_SFT_FILE, DRIVE_BACKUP_DIR / OUTPUT_SFT_FILE.name)
                if args.question_only:
                    shutil.copy2(contract_path, DRIVE_BACKUP_DIR / contract_path.name)
            except Exception as exc:
                tqdm.write(f"Drive backup failed: {exc}")

        batch_elapsed = time.perf_counter() - batch_started
        timeouts = sum(a["timeout"] for item in batch_metadata for a in item["attempts"])
        truncated = sum(a["finish_reason"] == "length" for item in batch_metadata for a in item["attempts"])
        overflow = sum(a["error_kind"] == "context_overflow" for item in batch_metadata for a in item["attempts"])
        tqdm.write(
            f"Batch {i // args.batch_size + 1}: kept={batch_accepted}/{len(batch_q)} "
            f"retry={len(turn2_items)} timeouts={timeouts} truncated={truncated} context_overflow={overflow} | "
            f"LLM={gen_time:.1f}s sandbox_wall={sandbox_wall:.1f}s "
            f"total={batch_elapsed:.1f}s ({batch_elapsed / len(batch_q):.2f}s/question)"
        )
        pbar.set_postfix(kept=accepted_count, timeouts=timeouts, retry=len(turn2_items))
        if use_wandb:
            total_seen = accepted_count + rejected_count
            wandb.log({
                "batch/gen_time_sec": round(gen_time, 2),
                "batch/sandbox_wall_sec": round(sandbox_wall, 2),
                "batch/elapsed_sec": round(batch_elapsed, 2),
                "batch/throughput_qps": round(len(batch_q) / max(0.01, batch_elapsed), 2),
                "batch/retries": len(turn2_items), "batch/timeouts": timeouts,
                "batch/truncated": truncated, "batch/context_overflow": overflow,
                "dataset/accepted": accepted_count, "dataset/rejected": rejected_count,
                "dataset/unanswerable": unanswerable_count,
                "dataset/acceptance_rate": round(accepted_count / max(1, total_seen), 4),
            })

    pbar.close()
    sft_out.close()
    log_out.close()

    print("\n================ TỔNG KẾT BƯỚC 1 (vLLM Engine) ================")
    print(f"✅ Số mẫu SFT đạt chuẩn (+1đ): {accepted_count}")
    print(f"❌ Số mẫu bị loại (sai/lỗi):   {rejected_count}")
    print(f"📂 File dataset sẵn sàng tại:  {OUTPUT_SFT_FILE}")
    if DRIVE_BACKUP_DIR:
        print(f"☁️ Đã sao lưu bản mới nhất lên Google Drive: {DRIVE_BACKUP_DIR / OUTPUT_SFT_FILE.name}")
    if use_wandb:
        wandb.finish()


if __name__ == "__main__":
    main()
