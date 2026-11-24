import json

with open(".agents/teamwork/explorer_1/cases_dump.json", "r", encoding="utf-8") as f:
    cases = json.load(f)

for idx, c in enumerate(cases, 1):
    print(f"[{idx:02d}] {c['id']} | {c['biz']} | Verdict: {c['verdict']} | Turns: {c['turns']}")
    print(f"     Q: {c['q']}")
    print(f"     Gold: ({c['gold_type']}) {c['gold_ans']}")
    print(f"     Pred: ({c['pred_type']}) {c['pred_ans']}")
    if c['errors']:
        print(f"     Errors in turns: {c['errors']}")
    print("-" * 80)
