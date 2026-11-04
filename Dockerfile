# =====================================================================
# Zalo AI Challenge 2026 — DataMate Dockerfile
# Single-model baseline: Qwen/Qwen2.5-Coder-7B-Instruct
# Hardware reference (Rule 7):
#   - 2 x NVIDIA RTX 5090 (Blackwell, 32 GB VRAM each = 64 GB total)
#   - CUDA >= 12.8 with matching PyTorch / vLLM build
#   - Fully offline execution (--network none, Rule 3)
#   - /data mounted read-only (:ro, Rule 5)
#   - Output at /result/submission.jsonl and logs at /result/logs/
#
# IMPORTANT SUBMISSION NOTICE:
# An image is NOT submission-ready until:
# 1. GPU wheels for PyTorch and vLLM are successfully built and verified on target CUDA 12.8.
# 2. Pretrained weights for Qwen2.5-Coder-7B-Instruct are copied into /workspace/models/Qwen2.5-Coder-7B-Instruct.
# 3. An offline end-to-end verification run on GPU completes within limits without network.
# =====================================================================

FROM nvidia/cuda:12.8.0-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TMPDIR=/tmp/datamate_work

# Install system dependencies & Python 3.11
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-dev \
    python3.11-venv \
    python3-pip \
    sqlite3 \
    git \
    curl \
    ca-certificates \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Install core and GPU Python dependencies
COPY requirements.txt /workspace/requirements.txt
COPY requirements-gpu.txt /workspace/requirements-gpu.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install -r /workspace/requirements.txt && \
    python -m pip install -r /workspace/requirements-gpu.txt

# Copy source code, configs, and predict.sh
COPY configs/ /workspace/configs/
COPY src/ /workspace/src/
COPY scripts/ /workspace/scripts/
COPY predict.sh /workspace/predict.sh
COPY README.md /workspace/README.md

# Offline weights must be placed in /workspace/models/Qwen2.5-Coder-7B-Instruct
# e.g.: COPY models/Qwen2.5-Coder-7B-Instruct /workspace/models/Qwen2.5-Coder-7B-Instruct
RUN mkdir -p /workspace/models/Qwen2.5-Coder-7B-Instruct /tmp/datamate_work /result /result/logs && \
    chmod +x /workspace/predict.sh

# Default command: run predict.sh reading from /data and writing to /result/submission.jsonl
CMD ["/workspace/predict.sh"]
