import json
from collections import Counter
from pathlib import Path

path = Path("verified_sft_dataset.jsonl")
if not path.exists():
    print(f"File {path} not found.")
    exit(1)

lines = []
with open(path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            lines.append(json.loads(line))

print("========================================")
print(f"📊 PHÂN TÍCH TỔNG QUAN TẬP VERIFIED SFT")
print("========================================")
print(f"Tổng số mẫu đạt chuẩn (+1đ): {len(lines)}")

biz_counts = Counter(item["business_id"] for item in lines)
print(f"\nPhủ sóng trên {len(biz_counts)} doanh nghiệp (biz):")
for biz, count in sorted(biz_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
    print(f"  - {biz}: {count} câu")

# Answer types
types = Counter()
multiturn_count = 0
for item in lines:
    msgs = item.get("messages", [])
    if len(msgs) > 3:
        multiturn_count += 1
    code = item.get("code", msgs[-1]["content"] if msgs else "")
    if '"type": "unanswerable"' in code:
        types["unanswerable"] += 1
    elif '"type": "table"' in code:
        types["table"] += 1
    elif '"type": "number"' in code:
        types["number"] += 1
    elif '"type": "string"' in code:
        types["string"] += 1
    elif '"type": "list"' in code:
        types["list"] += 1
    elif '"type": "boolean"' in code:
        types["boolean"] += 1
    elif '"type": "percent"' in code:
        types["percent"] += 1
    elif '"type": "date"' in code:
        types["date"] += 1
    else:
        types["other"] += 1

print("\nPhân bố kiểu dữ liệu đầu ra:")
for t, count in types.most_common():
    print(f"  - {t:<15}: {count:>4} câu ({count/len(lines)*100:.1f}%)")

print(f"\nSố lượng mẫu hội thoại đa lượt (multi-turn self-correction): {multiturn_count} câu")

# Train coverage
train_q_ids = set()
train_q_path = Path("data/train/questions.jsonl")
if train_q_path.exists():
    with open(train_q_path, "r", encoding="utf-8") as f:
        for line in f:
            train_q_ids.add(json.loads(line)["id"])
    sft_ids = set(item["id"] for item in lines)
    print(f"\nĐộ phủ trên tập train: {len(sft_ids)} / {len(train_q_ids)} ({len(sft_ids)/len(train_q_ids)*100:.1f}%)")

# Check safety
import ast
valid_ast = 0
for item in lines:
    code_str = item.get("code") or item["messages"][-1]["content"]
    code_body = code_str.split("```python")[1].split("```")[0].strip() if "```python" in code_str else code_str
    try:
        ast.parse(code_body)
        valid_ast += 1
    except SyntaxError:
        pass

print(f"Tính hợp lệ cú pháp Python AST: {valid_ast} / {len(lines)} ({valid_ast/len(lines)*100:.1f}%)")
print("========================================")
