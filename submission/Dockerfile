# DataMate submission image: OpenCode agent + Ollama + Ornith 1.5 9B (Q4_K_M GGUF). Offline at inference.
# Build context = this directory (run scripts/prepare_submission.py first).
FROM nvidia/cuda:12.8.1-base-ubuntu24.04

ARG NODE_VERSION=22.11.0
ARG OLLAMA_VERSION=0.40.7
ARG OPENCODE_VERSION=1.19.5

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 PIP_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    OPENCODE_DISABLE_MODELS_FETCH=1 OPENCODE_DISABLE_AUTOUPDATE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip ca-certificates curl zstd xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Node (needed by the opencode launcher), OpenCode and Ollama: downloaded at BUILD time only.
RUN curl -fsSL https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz \
      | tar -xJ -C /usr/local --strip-components=1 \
 && npm install -g opencode-ai@${OPENCODE_VERSION} \
 && curl -fL https://github.com/ollama/ollama/releases/download/v${OLLAMA_VERSION}/ollama-linux-amd64.tar.zst \
      | zstd -d | tar -x -C /usr/local \
 && ollama --version || true

COPY requirements.txt /code/requirements.txt
RUN pip install -r /code/requirements.txt

# Weights first so this big layer stays cached when only code changes.
COPY models/ /code/models/
COPY runtime/ /code/runtime/
COPY inference/ /code/inference/
COPY training_code/ /code/training_code/
COPY opencode_node_modules/ /opt/opencode_node_modules/
COPY predict.sh README.md /code/

# OpenCode installs its tool-plugin dependencies on first use; do it now so inference never needs the network.
RUN if [ -z "$(ls -A /opt/opencode_node_modules | grep -v '^\.keep$')" ]; then \
      mkdir -p /tmp/warm && cp -r /code/runtime/tools /tmp/warm/tools && cp /code/runtime/run.js /tmp/warm/run.js \
      && (HOME=/tmp/warm OPENCODE_CONFIG_DIR=/tmp/warm timeout 300 opencode debug config >/tmp/warm.log 2>&1 || true) \
      && (HOME=/tmp/warm OPENCODE_CONFIG_DIR=/tmp/warm timeout 300 opencode --pure debug config >>/tmp/warm.log 2>&1 || true) \
      && if [ -d /tmp/warm/node_modules ]; then cp -r /tmp/warm/node_modules/. /opt/opencode_node_modules/; fi; \
    fi; \
    ls -A /opt/opencode_node_modules | head -20; \
    sed -i 's/\r$//' /code/predict.sh && chmod +x /code/predict.sh \
 && pip freeze > /code/requirements.lock.txt

WORKDIR /code
ENTRYPOINT []
CMD ["bash", "/code/predict.sh"]
