# =====================================================================
# Zalo AI Challenge 2026 — DataMate Dockerfile
# Hardware reference (Rule 7):
#   - 2 x NVIDIA RTX 5090 (Blackwell, 32 GB VRAM each = 64 GB total)
#   - 512 GB RAM
#   - Requires CUDA >= 12.8 and matching PyTorch / vLLM build
#   - Network disabled at runtime (Rule 3: fully offline)
#   - /data mounted read-only (Rule 5)
#   - Collects output at /result/submission.jsonl
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

# Install Python dependencies
COPY requirements.txt /workspace/requirements.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install -r /workspace/requirements.txt

# Copy source code and configs
COPY configs/ /workspace/configs/
COPY src/ /workspace/src/
COPY scripts/ /workspace/scripts/
COPY README.md /workspace/README.md

# Create writable directories for temporary files and results
RUN mkdir -p /tmp/datamate_work /result

# Default command: run offline inference from /data to /result/submission.jsonl
CMD ["python", "scripts/run_inference.py", "--config", "configs/default_config.yaml", "--data-dir", "/data", "--output", "/result/submission.jsonl"]
