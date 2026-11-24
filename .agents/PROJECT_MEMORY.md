# PROJECT MEMORY — Zalo AI Challenge 2026: DataMate

## Overview & Stack
- **Project**: DataMate (Natural-Language Vietnamese Question Answering over Tabular Data).
- **Target Model**: `Qwen/Qwen2.5-14B-Instruct-1M` (14.7B params, strictly adheres to Rule 2 $\le 15\text{B}$).
- **Stack**: Python 3.10+, PyTorch/vLLM (CUDA $\ge 12.8$), pandas, sqlite3, openpyxl, pytest.
- **Evaluation Metric**: Penalized Accuracy (PA: +1.0 correct, 0.0 abstain, -1.0 wrong).

## Architecture & Key Entrypoints
- `src/agent/sandbox.py`: Isolated in-memory Python execution sandbox.
- `src/agent/solver.py`: ReAct multi-turn solver orchestrating thoughts, tool calls, and observations.
- `src/profiler/`: Extract structure & schemas of .csv, .xlsx, .sqlite.
- `src/time_resolver/`: Calendar lookups and relative date parsing (Rulebook §2).
- `src/postprocess/`: Unicode NFC normalization, formatting, and Abstain Gate.
- `predict.sh`: Competition Docker offline entrypoint.

## Key Decisions & Conventions
- **Raw Data Immutability**: `data/` is strictly read-only (`mode=ro`).
- **Domain-Agnostic Lean Helpers**: 6 core helpers (`explore_data`, `fuzzy_find`, `load_clean_df`, `resolve_date`, `emit_obs`, `emit_final`) replacing domain-hardcoded logic.
- **Ephemeral Thinking**: Keep 3-5 line Thought summaries between turns; strip raw `<think>` blocks to preserve context within 16,384 tokens.
- **Abstain-First Gating**: "Better to abstain than guess" — filter traps, empty matches, and unverified 0s convert to `"abstain"` to avoid -1.0 penalties.
- **Config Surgery**: Remove `dual_chunk_attention_config` from Qwen2.5-14B-Instruct-1M `config.json` before loading in standard Transformers/vLLM.

## Current Status & Next Steps
- **Handoff Plan Delivered**: `HANDOFF_PLAN.md` (1,191 lines) created at repository root, committed (`4e6ab89`), and pushed to remote branch `giabao` on `Thinh-gitgood/ZALO-AI-CHALLENGE-2026`.
- **Zero Scope Contamination**: `src/` and `notebooks/` untouched during planning phase.
- **Next Step**: Developer to implement Tasks 1–4 from `HANDOFF_PLAN.md` (implementing 6 helpers in sandbox, updating solver with Ephemeral Thinking, and running Colab evaluation).
