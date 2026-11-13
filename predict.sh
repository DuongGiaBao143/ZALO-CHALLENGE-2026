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
# Select configuration file: prefer DATAMATE_CONFIG if set, then DeepSeek-R1-14B config if present, else default_config.yaml
if [ -n "${DATAMATE_CONFIG:-}" ]; then
  CONFIG_FILE="$DATAMATE_CONFIG"
elif [ -f "/workspace/configs/deepseek_r1_14b_config.yaml" ]; then
  CONFIG_FILE="/workspace/configs/deepseek_r1_14b_config.yaml"
else
  CONFIG_FILE="/workspace/configs/default_config.yaml"
fi

mkdir -p "$(dirname "$OUTPUT_FILE")" "$LOGS_DIR" /tmp/datamate_work

python /workspace/scripts/run_inference.py \
  --config "$CONFIG_FILE" \
  --data-dir "$DATA_DIR" \
  --output "$OUTPUT_FILE" \
  --logs-dir "$LOGS_DIR"
