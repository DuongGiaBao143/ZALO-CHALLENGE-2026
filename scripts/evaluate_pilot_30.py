#!/usr/bin/env python3
"""Run evaluation on 30 Pilot Questions using trained LoRA adapter and report Penalized Accuracy (PA).

Compares results against the standard Qwen2.5-Coder-7B baseline:
  Baseline: PA = -0.4333 (Correct=1/30, Abstain=15/30, Wrong=14/30)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import yaml
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Allow HuggingFace Hub downloads when running pilot evaluation on Colab/Kaggle
os.environ.setdefault("DATAMATE_ALLOW_ONLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "0")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "0")

from src.agent.solver import DataMateAgent
from src.eval.scorer import evaluate_predictions
from src.schemas import QuestionItem, SubmissionItem

BASELINE_REPORT = {
    "total": 30,
    "correct": 1,
    "abstain": 15,
    "wrong": 14,
    "pa": -0.4333,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate LoRA Model on 30 Pilot Questions.")
    parser.add_argument(
        "--adapter-path",
        type=str,
        default=None,
        help="Optional path to trained LoRA adapter directory (omit or pass 'none' for pretrained base model).",
    )
    parser.add_argument(
        "--base-model",
        type=str,
        default="Qwen/Qwen2.5-Coder-7B-Instruct",
        help="Base model name or local directory.",
    )
    parser.add_argument(
        "--questions-file",
        type=str,
        default="result/baseline_7b_pilot/pilot_questions_30.jsonl",
        help="Path to 30 pilot questions JSONL.",
    )
    parser.add_argument(
        "--gold-file",
        type=str,
        default="eval_gold/pilot_gold_30.jsonl",
        help="Path to 30 pilot gold answers JSONL.",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/train",
        help="Root data directory containing shop folders (data/biz_xxx).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="result/eval_qwen7b_208_pilot",
        help="Directory to save evaluation predictions and logs.",
    )
    parser.add_argument(
        "--load-in-4bit",
        action="store_true",
        help="Enable 4-bit NF4 quantization (useful for low VRAM GPUs e.g. <= 16GB).",
    )
    parser.add_argument(
        "--dtype",
        type=str,
        default="float16",
        choices=["float16", "bfloat16", "auto"],
        help="Torch computation dtype.",
    )
    parser.add_argument('--backend', choices=['transformers', 'vllm'], default='transformers')
    parser.add_argument('--tensor-parallel-size', type=int, default=1)
    parser.add_argument('--gpu-memory-utilization', type=float, default=0.90)
    parser.add_argument('--enforce-eager', action='store_true')
    parser.add_argument('--max-model-len', type=int, default=16384)
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--no-prefix-caching', action='store_true', help='Disable prefix caching in vLLM')
    args = parser.parse_args()
    if args.tensor_parallel_size < 1 or not 0 < args.gpu_memory_utilization <= 1:
        parser.error('Tensor parallel size must be positive and GPU memory utilization must be in (0, 1]')
    return args


def main() -> None:
    args = parse_args()

    # Enable online model downloading if base model is Hugging Face ID
    os.environ.setdefault("DATAMATE_ALLOW_ONLINE", "1")
    if args.backend == 'transformers':
        os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    pred_path = output_dir / "submission.jsonl"
    report_path = output_dir / "evaluation_report.json"

    adapter_path = None
    if args.adapter_path and args.adapter_path.strip().lower() not in ("", "none", "null", "pretrained"):
        cand = Path(args.adapter_path).resolve()
        if not (cand / "adapter_config.json").exists():
            if (cand / "repaired" / "adapter_config.json").exists():
                adapter_path = cand / "repaired"
            elif (cand / "final_adapter" / "adapter_config.json").exists():
                adapter_path = cand / "final_adapter"
            else:
                print(f"❌ Không tìm thấy adapter_config.json tại: {cand}")
                sys.exit(1)
        elif (cand / "repaired" / "adapter_config.json").exists():
            adapter_path = cand / "repaired"
        else:
            adapter_path = cand

    print("============================================================")
    print("🚀 BẮT ĐẦU ĐÁNH GIÁ MÔ HÌNH TRÊN BỘ CÂU HỎI PILOT")
    print("============================================================")
    print(f"📦 Base Model   : {args.base_model}")
    print(f"🎯 LoRA Adapter : {adapter_path if adapter_path else 'None (Pretrained Base Model)'}")
    print(f"⚙️ Backend      : {args.backend} | TP={args.tensor_parallel_size}")
    print(f"📋 Questions    : {args.questions_file}")
    print(f"🏆 Gold Answers : {args.gold_file}")
    print(f"📂 Output Dir   : {output_dir}")

    # Dò tìm base model local nếu có (e.g. Kaggle path hoặc Colab path)
    base_model_path = args.base_model
    kaggle_candidate = Path("/kaggle/input/models/qwen-lm/qwen2.5-coder/transformers/7b-instruct/1")
    colab_candidate = Path("/content/models/Qwen2.5-Coder-7B-Instruct")
    if Path(args.base_model).is_dir():
        base_model_path = str(Path(args.base_model).resolve())
    elif "qwen2.5-coder-7b" in args.base_model.lower():
        if kaggle_candidate.exists() and (kaggle_candidate / "config.json").exists():
            base_model_path = str(kaggle_candidate)
            print(f"💡 Phát hiện base model Kaggle tại: {base_model_path}")
        elif colab_candidate.exists() and (colab_candidate / "config.json").exists():
            base_model_path = str(colab_candidate)
            print(f"💡 Phát hiện base model Colab tại: {base_model_path}")

    # Tự động tối ưu hóa 4-bit nếu GPU có VRAM <= 16GB (e.g. T4 15GB hoặc RTX 4050 6GB)
    import torch
    use_4bit = args.load_in_4bit
    if torch.cuda.is_available():
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        print(f"🔥 GPU: {torch.cuda.get_device_name(0)} ({vram_gb:.2f} GB VRAM)")
        if args.backend == 'transformers' and vram_gb < 16.0 and not use_4bit:
            print(f"⚡ VRAM < 16GB -> Tự động bật chế độ 4-bit NF4 (~4.5GB VRAM) để chạy mượt mà!")
            use_4bit = True
        elif args.backend == 'vllm':
            if torch.cuda.device_count() < args.tensor_parallel_size:
                raise RuntimeError('Not enough GPUs for the requested tensor parallel size')
            is_turing_or_older = torch.cuda.get_device_capability(0) < (8, 0)
            if vram_gb < 16.0 or is_turing_or_older:
                print(f"⚡ VRAM < 16GB / Turing GPU (T4) -> Tự động bật enforce_eager và tắt prefix_caching để tránh lỗi 64KB Shared Memory!")
                args.enforce_eager = True
                args.no_prefix_caching = True
                if args.max_model_len > 8192:
                    args.max_model_len = 8192
                # FP16 7B weights alone are ~14.2 GiB: they cannot fit one T4 without TP=2.
                if args.tensor_parallel_size == 1 and not use_4bit:
                    print("⚡ 7B FP16 (~14.2 GiB) không vừa 1 T4 -> vLLM bitsandbytes 4-bit + LoRA")
                    use_4bit = True
            prefix_caching_enabled = not args.no_prefix_caching
            print(f'vLLM: {args.dtype}, TP={args.tensor_parallel_size}, prefix caching: {prefix_caching_enabled}')
        elif vram_gb >= 16.0:
            print(f"🚀 VRAM lớn ({vram_gb:.1f}GB) -> Chạy native {args.dtype} đầy đủ tốc độ!")
    print("============================================================\n")

    config = {
        "model": {
            "name_or_path": args.base_model,
            "local_model_dir": base_model_path,
            "backend": args.backend,
            "tensor_parallel_size": args.tensor_parallel_size,
            "gpu_memory_utilization": args.gpu_memory_utilization,
            "enforce_eager": args.enforce_eager,
            "enable_prefix_caching": prefix_caching_enabled if "prefix_caching_enabled" in locals() else True,
            "max_num_seqs": 1,
            "adapter_path": str(adapter_path) if adapter_path else None,
            "dtype": args.dtype,
            "load_in_4bit": use_4bit,
            "max_model_len": args.max_model_len,
            "max_tokens": args.max_tokens,
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 42,
        },
        "agent": {
            "max_turns": 3,
            "max_code_executions": 3,
            "sandbox_timeout_sec": 25,
            "max_sample_rows": 5,
            "max_unique_categorical": 25,
        },
        "paths": {
            "data_dir": args.data_dir,
            "output_file": str(pred_path),
            "logs_dir": str(logs_dir),
            "work_dir": str(output_dir / "tmp_work"),
        },
    }

    questions_file = Path(args.questions_file)
    if not questions_file.exists():
        print(f"❌ Không tìm thấy file câu hỏi: {questions_file}")
        sys.exit(1)

    questions: List[QuestionItem] = []
    with open(questions_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(QuestionItem.from_dict(json.loads(line)))

    print(f"🔄 Đang khởi tạo DataMateAgent và nạp LoRA...")
    t0 = time.time()
    agent = DataMateAgent(config=config, data_dir=Path(args.data_dir))
    init_time = time.time() - t0
    print(f"✅ Khởi tạo agent thành công ({init_time:.2f}s)!\n")

    predictions: List[Dict[str, Any]] = []
    inference_started = time.time()
    with open(pred_path, "w", encoding="utf-8") as out_f:
        pbar = tqdm(questions, desc="Solving pilot questions", dynamic_ncols=True)
        for q_item in pbar:
            q_t0 = time.time()
            try:
                sub_item, trace = agent.answer_question_with_trace(q_item)
            except Exception as exc:
                sub_item = SubmissionItem.abstain(q_item.id, reason=f"Runtime exception: {exc}")
                trace = {"id": q_item.id, "error": str(exc)}

            pred_dict = sub_item.to_dict()
            predictions.append(pred_dict)
            out_f.write(json.dumps(pred_dict, ensure_ascii=False) + "\n")
            out_f.flush()

            # Write trace log
            log_item_path = logs_dir / f"{q_item.id}.json"
            log_item_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")

    inference_seconds = time.time() - inference_started
    print(f"\n✅ Đã hoàn tất {len(predictions)} câu trong {inference_seconds:.1f}s!")
    print(f"📁 Kết quả lưu tại: {pred_path}\n")

    # Đánh giá điểm PA
    gold_file = Path(args.gold_file)
    if not gold_file.exists():
        print(f"⚠️ Không tìm thấy file đáp án vàng tại: {gold_file}. Bỏ qua bước tính điểm PA.")
        return

    golds: List[Dict[str, Any]] = []
    with open(gold_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                golds.append(json.loads(line))

    eval_report = evaluate_predictions(predictions=predictions, references=golds)

    # In báo cáo chi tiết
    print("=" * 65)
    print(f"📊 BÁO CÁO ĐÁNH GIÁ PENALIZED ACCURACY (PA) — {len(golds)} CÂU HỎI")
    print("=" * 65)
    print(eval_report.format_summary())

    if len(golds) == BASELINE_REPORT["total"] and "pilot_questions_30" in str(args.questions_file):
        delta_pa = eval_report.penalized_accuracy - BASELINE_REPORT["pa"]
        delta_correct = eval_report.correct - BASELINE_REPORT["correct"]
        delta_wrong = eval_report.wrong - BASELINE_REPORT["wrong"]

        print("=" * 65)
        print("📈 SO SÁNH VỚI BASELINE (Qwen 7B Zero-Shot):")
        print("=" * 65)
        print(f"  • Baseline PA Score : {BASELINE_REPORT['pa']:+.4f} (Đúng: {BASELINE_REPORT['correct']}, Sai: {BASELINE_REPORT['wrong']}, Abstain: {BASELINE_REPORT['abstain']})")
        print(f"  • Trained LoRA Model: {eval_report.penalized_accuracy:+.4f} (Đúng: {eval_report.correct}, Sai: {eval_report.wrong}, Abstain: {eval_report.abstain})")
        print(f"  -------------------------------------------------------------")
        print(f"  🎯 Mức cải thiện Δ PA: {delta_pa:+.4f} điểm")
        print(f"  🎯 Tăng số câu đúng : {delta_correct:+d} câu")
        print(f"  🎯 Giảm số câu sai  : {-delta_wrong:+d} câu (tránh bị phạt -1 điểm)")
        print("=" * 65)

    # Lưu kết quả báo cáo ra file json
    report_dict = {
        "model_id": args.base_model,
        "adapter_path": str(adapter_path),
        "backend": args.backend,
        "tensor_parallel_size": args.tensor_parallel_size,
        "initialization_seconds": init_time,
        "inference_seconds": inference_seconds,
        "seconds_per_question": inference_seconds / len(predictions) if predictions else None,
        "total_questions": eval_report.total,
        "correct": eval_report.correct,
        "abstain": eval_report.abstain,
        "wrong": eval_report.wrong,
        "penalized_accuracy": eval_report.penalized_accuracy,
        "baseline_pa": BASELINE_REPORT["pa"],
        "delta_pa": delta_pa,
    }
    report_path.write_text(json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📄 Đã lưu báo cáo chi tiết tại: {report_path}")


if __name__ == "__main__":
    main()
