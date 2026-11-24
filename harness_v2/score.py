"""Chấm một file predictions.jsonl trên một EvalSet và in báo cáo; so hai lần chạy với nhau."""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.eval.scorer import score_single_answer  # noqa: E402

from harness_v2.evalsets import EvalSet, get, load_jsonl  # noqa: E402


def load_preds(path: Path) -> dict[str, dict]:
    return {r["id"]: r for r in load_jsonl(path)} if path.exists() else {}


def score_set(es: EvalSet, preds: dict[str, dict]) -> dict:
    per, by_type, reasons = {}, collections.defaultdict(collections.Counter), collections.Counter()
    elapsed = []
    for item in es.items:
        q, gold = item["id"], es.gold[item["id"]]
        p = preds.get(q)
        if p is None:
            verdict, score, reason = "abstain", 0, "no_prediction"
        else:
            verdict, score = score_single_answer({"id": q, "type": p.get("type"), "answer": p.get("answer")}, gold)
            reason = p.get("reason") if p.get("type") == "abstain" else None
            if p.get("elapsed") is not None:
                elapsed.append(float(p["elapsed"]))
        if verdict == "abstain":
            reasons[reason or "abstain"] += 1
        per[q] = {"verdict": verdict, "score": score, "gold_type": gold["type"], "reason": reason}
        by_type[gold["type"]][verdict] += 1
    n = len(es.items)
    c = sum(r["verdict"] == "correct" for r in per.values())
    w = sum(r["verdict"] == "wrong" for r in per.values())
    return {
        "set": es.name, "n": n, "correct": c, "wrong": w, "abstain": n - c - w,
        "PA": round((c - w) / n, 4), "accuracy_when_answered": round(c / (c + w), 4) if c + w else None,
        "by_type": {t: dict(v) for t, v in sorted(by_type.items())}, "abstain_reasons": dict(reasons.most_common()),
        "mean_elapsed_sec": round(sum(elapsed) / len(elapsed), 1) if elapsed else None, "per_question": per,
    }


def print_report(rep: dict) -> None:
    acc = rep["accuracy_when_answered"]
    print(f"[{rep['set']}] n={rep['n']} | đúng {rep['correct']} | sai {rep['wrong']} | abstain {rep['abstain']} | PA = {rep['PA']:+.3f}"
          + (f" | chính xác khi có trả lời {acc:.0%}" if acc is not None else ""))
    print("  theo loại:", "; ".join(f"{t}: {dict(v)}" for t, v in rep["by_type"].items()))
    print("  lý do abstain:", rep["abstain_reasons"] or "-", "| thời gian TB:", rep["mean_elapsed_sec"])


def compare(a: dict, b: dict) -> None:
    flips = [(q, a["per_question"][q]["verdict"], b["per_question"][q]["verdict"]) for q in a["per_question"]
             if q in b["per_question"] and a["per_question"][q]["verdict"] != b["per_question"][q]["verdict"]]
    print(f"PA {a['PA']:+.3f} -> {b['PA']:+.3f} | {len(flips)} câu đổi kết quả")
    for q, x, y in flips:
        print(f"  {q}: {x} -> {y}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", required=True)
    ap.add_argument("--preds", required=True, type=Path)
    ap.add_argument("--compare", type=Path, help="predictions.jsonl khác để so từng câu")
    ap.add_argument("--save", type=Path, help="ghi báo cáo json")
    a = ap.parse_args()
    es = get(a.set)
    rep = score_set(es, load_preds(a.preds))
    print_report(rep)
    if a.compare:
        compare(score_set(es, load_preds(a.compare)), rep)
    if a.save:
        a.save.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
