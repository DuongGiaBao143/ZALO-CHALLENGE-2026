#!/usr/bin/env bash
# =====================================================================
# Zalo AI Challenge 2026 — DataMate Official Prediction Entrypoint
# Reads test split from /data, writes /result/submission.jsonl and
# per-question logs to /result/logs/
# =====================================================================
set -euo pipefail

DATA_DIR="${1:-/data}"
OUTPUT_FILE="${2:-/result/submission.jsonl}"
LOGS_DIR="${3:-/result/logs}"

mkdir -p "$(dirname "$OUTPUT_FILE")" "$LOGS_DIR" /tmp/datamate_work

python /workspace/scripts/run_inference.py \
  --config /workspace/configs/default_config.yaml \
  --data-dir "$DATA_DIR" \
  --output "$OUTPUT_FILE" \
  --logs-dir "$LOGS_DIR"
