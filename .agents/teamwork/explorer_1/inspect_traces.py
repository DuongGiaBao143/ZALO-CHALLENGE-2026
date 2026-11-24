import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(".").resolve()
sys.path.insert(0, str(PROJECT_ROOT))

logs_dir = Path("result/qwen25_14b_1m_code_only_rulebook_20261111_155610/eval_dev_30_colab_a100_40gb_ctx16384/logs")
with open("eval_gold/unseen_gold_30.jsonl", "r", encoding="utf-8") as f:
    golds = {l["id"]: l for l in (json.loads(x) for x in f if x.strip())}
with open("result/qwen25_14b_1m_code_only_rulebook_20261111_155610/eval_dev_30_colab_a100_40gb_ctx16384/submission.jsonl", "r", encoding="utf-8") as f:
    subs = {l["id"]: l for l in (json.loads(x) for x in f if x.strip())}

from src.eval.scorer import score_single_answer

details = []
for qid, gold in golds.items():
    pred = subs.get(qid)
    verdict, score = score_single_answer(pred, gold)
    log_path = logs_dir / f"{qid}.json"
    with open(log_path, "r", encoding="utf-8") as f:
        log = json.load(f)
    
    attempts = log.get("attempts", [])
    att_summaries = []
    for idx, att in enumerate(attempts, 1):
        succ = att.get("success")
        code = att.get("generated_code") or ""
        out_kind = att.get("kind")
        p_out = att.get("parsed_output") or {}
        err = att.get("error_message") or att.get("stderr") or ""
        att_summaries.append({
            "turn": idx,
            "success": succ,
            "kind": out_kind,
            "parsed": p_out,
            "error_tail": err.strip().splitlines()[-1] if err else "",
            "code_len": len(code),
        })
    details.append({
        "id": qid,
        "biz": log.get("business_id"),
        "question": log.get("question"),
        "as_of_date": log.get("as_of_date"),
        "gold_type": gold["type"],
        "gold_answer": gold["answer"],
        "pred_type": pred["type"] if pred else None,
        "pred_answer": pred["answer"] if pred else None,
        "verdict": verdict,
        "attempts": att_summaries,
    })

with open(".agents/teamwork/explorer_1/full_case_details.json", "w", encoding="utf-8") as f:
    json.dump(details, f, ensure_ascii=False, indent=2)

print(f"Processed {len(details)} case details.")
