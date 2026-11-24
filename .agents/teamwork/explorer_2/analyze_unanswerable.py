import json
from pathlib import Path

train_ans = Path('d:/PROJECT/ZALO-AI-CHALLENGE-2026/data/train/answers.jsonl')
train_q = Path('d:/PROJECT/ZALO-AI-CHALLENGE-2026/data/train/questions.jsonl')

questions = {json.loads(line)['id']: json.loads(line) for line in train_q.read_text(encoding='utf-8').splitlines() if line.strip()}
answers = [json.loads(line) for line in train_ans.read_text(encoding='utf-8').splitlines() if line.strip()]

unans = [a for a in answers if a.get('type') == 'unanswerable']
print(f"Total questions: {len(answers)}, Total unanswerable: {len(unans)} ({len(unans)/len(answers)*100:.2f}%)")

# Categorize reasons
reasons = {}
for a in unans:
    qid = a['id']
    q = questions[qid]
    r = a.get('reason', 'no_reason')
    # print sample
    print(f"[{q['business_id']}] ({q['as_of_date']}) {q['question']}")
    print(f"   -> reason: {r}")
