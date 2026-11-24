"""Đổi trace của harness OpenCode cũ (traces/<qid>.json) sang predictions.jsonl để chấm trên cùng thước đo.

Dùng làm mốc so sánh: python -m harness_v2.import_traces traces runs/opencode_old/predictions.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def convert(trace: dict) -> dict:
    p = trace.get("prediction") or {}
    rec = {"id": trace["id"], "type": p.get("type", "abstain"), "answer": p.get("answer"),
           "elapsed": trace.get("elapsed_sec"), "finish": trace.get("finish_reason"), "tokens": trace.get("tokens")}
    if rec["type"] == "abstain":
        rec["reason"] = trace.get("abstain_reason") or "abstain"
    return rec


def main(src: Path, out: Path) -> None:
    recs = []
    for f in sorted(src.glob("*.json")):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print("bỏ qua (không đọc được):", f.name)
            continue
        if isinstance(t, dict) and "id" in t and "prediction" in t:
            recs.append(convert(t))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    print(f"đã đổi {len(recs)} trace -> {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
