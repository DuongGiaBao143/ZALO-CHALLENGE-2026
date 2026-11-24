"""Chạy một solver trên một EvalSet, song song, ghi predictions.jsonl (chạy tiếp được nếu bị ngắt).

Solver là hàm `solve(item: dict, split_dir: Path) -> dict` trả {"type", "answer", ...}; các khoá tuỳ chọn:
reason (lý do abstain), elapsed (giây), tokens, finish. Solver chỉ nhận item và thư mục split: không có đáp án.
Ví dụ: python -m harness_v2.run --set private_50 --solver harness_v2.solvers.dummy:solve --out runs/dummy/predictions.jsonl
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness_v2.evalsets import EvalSet, get  # noqa: E402
from harness_v2.score import load_preds, print_report, score_set  # noqa: E402


def abstain(reason: str, **extra) -> dict:
    return {"type": "abstain", "answer": None, "reason": reason, **extra}


def run(es: EvalSet, solve, out: Path, workers: int = 4, limit: int | None = None) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    done = load_preds(out)
    todo = [it for it in es.items if it["id"] not in done][:limit]
    lock = threading.Lock()
    print(f"{es.name}: {len(es)} câu | đã có {len(done)} | chạy {len(todo)} | {workers} luồng", flush=True)

    def work(item: dict) -> None:
        t0 = time.time()
        try:
            rec = dict(solve(dict(item), es.split_dir))
        except Exception as exc:   # một câu lỗi không được làm hỏng cả lượt chạy
            rec = abstain(f"solver_error:{type(exc).__name__}")
        rec["id"] = item["id"]
        rec.setdefault("elapsed", round(time.time() - t0, 2))
        with lock:
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done[item["id"]] = rec
            print(f"  [{len(done)}/{len(es)}] {item['id']} -> {rec.get('type')} {str(rec.get('answer'))[:60]} "
                  f"| {rec['elapsed']}s" + (f" | {rec['reason']}" if rec.get("reason") else ""), flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, todo))
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", required=True)
    ap.add_argument("--solver", required=True, help="module:function")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    mod, fn = a.solver.split(":")
    es = get(a.set)
    preds = run(es, getattr(importlib.import_module(mod), fn), a.out, a.workers, a.limit)
    print_report(score_set(es, preds))


if __name__ == "__main__":
    main()
