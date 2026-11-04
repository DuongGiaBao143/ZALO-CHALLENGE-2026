import json

with open("verified_sft_dataset.jsonl", encoding="utf-8") as f:
    rows = [json.loads(l) for l in f if l.strip()]

lens = []
for r in rows:
    # Estimate characters
    tot_chars = len(r["code"]) if "code" in r else sum(len(m["content"]) for m in r["messages"])
    lens.append((r["id"], tot_chars))

lens.sort(key=lambda x: x[1], reverse=True)
print("Top 5 longest by chars (code only for compact records):", lens[:5])
print("Shortest by chars:", lens[-5:])
