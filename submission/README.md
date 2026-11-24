# Zalo AI Challenge 2026 - DataMate - solution README

Team image: `zaic2026_datamate_<team_name>:final`. Entry point: `bash /code/predict.sh` (no arguments).

## Approach

A small agent answers each question by reading the business files and running code, with no human input.

1. `predict.sh` -> `/code/inference/run_inference.py` reads `/data/questions.jsonl`.
2. For every question the shop folder `/data/data/<business_id>/` is copied to a scratch directory.
3. An OpenCode 1.19.5 agent (greedy, temperature 0, seed 42, at most 14 steps) talks to a local Ollama
   server on 127.0.0.1 that serves the model. The system prompt contains the split's `rulebook.md`
   and a fixed workflow; the agent reads the shop `README.md`, inspects tables and sheets, then answers.
4. Three tools are exposed (`runtime/tools/*.js` -> `runtime/bridge.py`):
   `inspect_table` (files, sheets, columns, label values), `aggregate` (count_distinct on CSV) and
   `run_python` (the model writes pandas/openpyxl/sqlite code; it runs in a subprocess with a timeout, read-only on the data).
   Helpers available to that code: `explore_data, fuzzy_find, load_clean_df, resolve_date, emit_obs, emit_final`
   (+ Vietnamese number/date parsers). Code ends with `emit_final(answer, type=..., evidence=...)`.
5. The answer is taken from the validated `emit_final` / `aggregate` payload (the model's final text is
   only used when no tool result exists), checked against the output schema, and written immediately.
   If nothing can be verified the question is answered `abstain`.
6. Two GPUs, `DAEMONS_PER_GPU` (default 2) Ollama servers per GPU, one worker per server.
   A global budget (5 h 40 min including model loading) stops new questions; unfinished ones are written as abstain.
   Answers are appended to `/result/submission.jsonl` as soon as they are known.

No question id or business id is used in any logic. No network is used at inference
(OpenCode and Ollama only talk to loopback; `HF_HUB_OFFLINE=1`).

## Models

| Item | Value |
|---|---|
| Model | Ornith 1.5 9B (dense), public source: https://huggingface.co/ornith-ai/Ornith-1.5-9B |
| Run as | Ollama build `ornith-1.5:9b`, GGUF Q4_K_M, 6,550,813,701 bytes, plus Modelfile overlay `ornith15-datamate-pilot-8k` (parameters only) |
| Ollama manifest digest | `57ad8bec8adf0a704a07a26adb2abf9edae310ba0fd3cef575d02dac1af69bb5` |
| Weight blobs (sha256) | `852922174ee4f76621df26105333f1dfe2171cdfb60ebe5a4b013836681a8a77`, `2635637dd72b4d39a97331373a73366b69a0a6a14151b2a1da0a97b311e2461f` |
| Licence | MIT |
| Parameters | 9,653,104,368 (about 9.65B, from the Hugging Face safetensors metadata); the only model in the pipeline, below the 15B limit |
| Original release date | 2026-08-18 (creation date of the Hugging Face repository; last modified 2026-08-23) |
| Fixed revision | Hugging Face commit `489cb97981b8654bcfcf30ce1f94ed1b62e07b53` (BF16 reference weights); the weights actually run are the Ollama GGUF build above, identified by the sha256 digests in this table |
| Fine-tuning | none |

Software: Ollama 0.40.7 (MIT), OpenCode 1.19.5 (MIT), Python packages in `requirements.lock.txt`.

## Data

No training data, no synthetic data, no public/private test data used for any purpose.
The rulebook and calendar read at run time come from `/data`. `training_code/` documents that nothing was trained.

## Folder layout in the image

```
/code/predict.sh                 entry point
/code/README.md
/code/requirements.txt, requirements.lock.txt
/code/inference/                 run_inference.py (orchestration, logs), agent_runner.py (per-question agent run)
/code/runtime/                   bridge.py, run.js, tools/*.js, src/ (sandbox + helpers + schemas)
/code/models/ollama/             Ollama model store (weights and manifest)
/code/training_code/             README (no training), data_manifest.json
/opt/opencode_node_modules/      OpenCode tool dependencies installed at build time
```

## Output and logs

* `/result/submission.jsonl`: one `{"id","type","answer"}` per question, flushed per answer.
* `/result/logs/questions.jsonl`: one record per question with `id`, `answer`, `elapsed_ms` (question start to final answer),
  `thinking` (reasoning as generated, null if none), `code` (code actually executed by the sandbox, null if none), `output`.
* `/result/logs/traces/<id>.json`: full agent trace (prompts, tool calls and results). `/result/logs/run.log`, `ollama_daemon_*.log`.

## Reproducibility

Greedy decoding (temperature 0, seed 42, fixed `num_batch`), one request at a time per server.
Parallel servers can change timing but not the per-question prompt. Run the image twice on the same input and compare.

## Build and run

```
python scripts/prepare_submission.py          # gathers runtime + model blobs into submission/
docker build --platform linux/amd64 -t zaic2026_datamate_<team_name>:final submission/
docker run --rm --gpus '"device=0,1"' --network none --shm-size=16g --entrypoint bash \
  -v /path/to/data:/data:ro -v /path/to/out:/result zaic2026_datamate_<team_name>:final /code/predict.sh
```
