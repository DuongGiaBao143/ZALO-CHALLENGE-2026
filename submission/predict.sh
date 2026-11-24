#!/usr/bin/env bash
# Entry point: reads /data, writes /result/submission.jsonl and /result/logs/. No arguments.
# Fixed defaults (model, seed, temperature, concurrency) live in /code/inference; the environment
# variables below only exist so the image can be smoke-tested locally (e.g. DATAMATE_LIMIT=10).
set -u
export PYTHONUNBUFFERED=1 PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export DATAMATE_SPLIT_DIR="${DATAMATE_SPLIT_DIR:-/data}"
export DATAMATE_RESULT_DIR="${DATAMATE_RESULT_DIR:-/result}"
export DATAMATE_RUNTIME_DIR="${DATAMATE_RUNTIME_DIR:-/code/runtime}"
export DATAMATE_OLLAMA_MODELS="${DATAMATE_OLLAMA_MODELS:-/code/models/ollama}"

mkdir -p "$DATAMATE_RESULT_DIR/logs"
python3 /code/inference/run_inference.py
rc=$?

# Safety net: the run must always leave a complete submission.jsonl (missing ids would count as abstain anyway).
if [ ! -s "$DATAMATE_RESULT_DIR/submission.jsonl" ] && [ -f "$DATAMATE_SPLIT_DIR/questions.jsonl" ]; then
  python3 - <<'PY'
import json, os
d, r = os.environ["DATAMATE_SPLIT_DIR"], os.environ["DATAMATE_RESULT_DIR"]
with open(f"{d}/questions.jsonl", encoding="utf-8-sig") as f, open(f"{r}/submission.jsonl", "w", encoding="utf-8") as o:
    for line in f:
        if line.strip():
            o.write(json.dumps({"id": json.loads(line)["id"], "type": "abstain", "answer": None}) + "\n")
PY
fi
exit 0
