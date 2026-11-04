"""Sample a clean unseen test set from data/train, guaranteeing ZERO overlap with SFT dataset."""
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 1. Load SFT IDs
sft_file = ROOT / "verified_sft_dataset.jsonl"
sft_ids = set()
with open(sft_file, "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            sft_ids.add(json.loads(line)["id"])
print(f"Loaded {len(sft_ids)} SFT IDs to exclude.")

# 2. Load Train Questions & Answers
q_file = ROOT / "data" / "train" / "questions.jsonl"
a_file = ROOT / "data" / "train" / "answers.jsonl"

with open(q_file, "r", encoding="utf-8") as f:
    all_questions = [json.loads(l) for l in f if l.strip()]

with open(a_file, "r", encoding="utf-8") as f:
    all_answers = {json.loads(l)["id"]: json.loads(l) for l in f if l.strip()}

# 3. Filter unseen
unseen_questions = [q for q in all_questions if q["id"] not in sft_ids]
print(f"Total train questions: {len(all_questions)}")
print(f"Clean Unseen candidates: {len(unseen_questions)}")

# Verify 0 overlap
assert len(set(q["id"] for q in unseen_questions).intersection(sft_ids)) == 0

# Group unseen by business and type
by_biz_type = defaultdict(lambda: defaultdict(list))
for q in unseen_questions:
    ans = all_answers.get(q["id"])
    if ans:
        t = ans["type"]
        by_biz_type[q["business_id"]][t].append(q)

def sample_stratified(target_count: int, seed: int = 42):
    rng = random.Random(seed)
    
    # Stratified target distribution for 30 questions:
    # 8 types: number(9), percent(4), list(4), date(4), string(3), unanswerable(3), table(2), boolean(1)
    if target_count == 30:
        type_targets = {
            "number": 9,
            "percent": 4,
            "list": 4,
            "date": 4,
            "string": 3,
            "unanswerable": 3,
            "table": 2,
            "boolean": 1,
        }
    elif target_count == 50:
        type_targets = {
            "number": 16,
            "percent": 8,
            "list": 6,
            "date": 6,
            "string": 5,
            "unanswerable": 4,
            "table": 3,
            "boolean": 2,
        }
    else:
        raise ValueError(f"Unsupported target_count {target_count}")

    sampled_questions = []
    sampled_gold = []

    # For each type, sample from different businesses as much as possible
    for ans_type, count in type_targets.items():
        candidates = []
        for biz in sorted(by_biz_type.keys()):
            qs = by_biz_type[biz].get(ans_type, [])
            for q in qs:
                candidates.append(q)
        
        # Deterministic shuffle
        rng.shuffle(candidates)
        selected = candidates[:count]
        if len(selected) < count:
            raise ValueError(f"Not enough candidates for type {ans_type}: needed {count}, got {len(selected)}")
        
        for q in selected:
            sampled_questions.append(q)
            sampled_gold.append(all_answers[q["id"]])

    # Sort by ID
    paired = sorted(zip(sampled_questions, sampled_gold), key=lambda x: x[0]["id"])
    return [p[0] for p in paired], [p[1] for p in paired]

# Generate 30 questions
q30, g30 = sample_stratified(30, seed=42)
out_q30 = ROOT / "result" / "unseen_eval_30" / "questions.jsonl"
out_g30 = ROOT / "eval_gold" / "unseen_gold_30.jsonl"
out_q30.parent.mkdir(parents=True, exist_ok=True)
out_g30.parent.mkdir(parents=True, exist_ok=True)

with open(out_q30, "w", encoding="utf-8") as f:
    for q in q30:
        f.write(json.dumps(q, ensure_ascii=False) + "\n")

with open(out_g30, "w", encoding="utf-8") as f:
    for g in g30:
        f.write(json.dumps(g, ensure_ascii=False) + "\n")

print(f"\n✅ Created 30 unseen questions at: {out_q30}")
print(f"✅ Created 30 unseen gold answers at: {out_g30}")
print(f"Overlap with SFT: {len(set(q['id'] for q in q30).intersection(sft_ids))}")
print("Answer type distribution in 30 unseen:", Counter(g["type"] for g in g30))

# Generate 50 questions
q50, g50 = sample_stratified(50, seed=42)
out_q50 = ROOT / "result" / "unseen_eval_50" / "questions.jsonl"
out_g50 = ROOT / "eval_gold" / "unseen_gold_50.jsonl"
out_q50.parent.mkdir(parents=True, exist_ok=True)
out_g50.parent.mkdir(parents=True, exist_ok=True)

with open(out_q50, "w", encoding="utf-8") as f:
    for q in q50:
        f.write(json.dumps(q, ensure_ascii=False) + "\n")

with open(out_g50, "w", encoding="utf-8") as f:
    for g in g50:
        f.write(json.dumps(g, ensure_ascii=False) + "\n")

print(f"\n✅ Created 50 unseen questions at: {out_q50}")
print(f"✅ Created 50 unseen gold answers at: {out_g50}")
print(f"Overlap with SFT: {len(set(q['id'] for q in q50).intersection(sft_ids))}")
print("Answer type distribution in 50 unseen:", Counter(g["type"] for g in g50))
