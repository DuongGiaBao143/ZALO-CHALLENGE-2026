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

out = []
for qid, gold in golds.items():
    pred = subs.get(qid)
    verdict, score = score_single_answer(pred, gold)
    log_path = logs_dir / f"{qid}.json"
    log = {}
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)
    
    attempts = log.get("attempts", [])
    errors = []
    codes = []
    for att in attempts:
        codes.append(att.get("generated_code", ""))
        err = att.get("error_message") or att.get("stderr")
        if err:
            errors.append(err.strip()[-200:])
            
    out.append({
        "id": qid,
        "biz": log.get("business_id"),
        "q": log.get("question"),
        "as_of_date": log.get("as_of_date"),
        "gold_type": gold["type"],
        "gold_ans": gold["answer"],
        "pred_type": pred["type"] if pred else None,
        "pred_ans": pred["answer"] if pred else None,
        "verdict": verdict,
        "score": score,
        "turns": len(attempts),
        "errors": errors,
        "final_code": codes[-1] if codes else "",
    })

with open(".agents/teamwork/explorer_1/cases_dump.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"Dumped {len(out)} cases successfully.")
