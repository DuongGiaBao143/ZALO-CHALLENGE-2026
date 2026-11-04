import json

with open("verified_sft_dataset.jsonl", "r", encoding="utf-8") as f:
    lines = [json.loads(line) for line in f if line.strip()]

if all(set(row) == {"id", "business_id", "code"} for row in lines):
    import ast
    assert len({row['id'] for row in lines}) == len(lines)
    for row in lines:
        assert all(isinstance(value, str) and value.strip() for value in row.values())
        ast.parse(row['code'])
    print(f"Total lines: {len(lines)}; valid compact records: id, business_id, code")
    raise SystemExit(0)

sys_prompts = set(l["messages"][0]["content"] for l in lines)
print(f"Total lines: {len(lines)}")
print(f"Number of unique system prompts: {len(sys_prompts)}")
formats = set(l.get("prompt_format") for l in lines)
print(f"Prompt formats: {formats}")
msg_lens = set(len(l["messages"]) for l in lines)
print(f"Message lengths: {msg_lens}")

for idx, l in enumerate(lines):
    msgs = l["messages"]
    if [m["role"] for m in msgs] != ["system"] + ["user", "assistant"] * ((len(msgs) - 1) // 2):
        print(f"Invalid roles at {idx}: {[m['role'] for m in msgs]}")
        break
    if not all(isinstance(m["content"], str) and m["content"].strip() for m in msgs):
        print(f"Empty content at {idx}")
        break
else:
    print("All roles and content valid!")
