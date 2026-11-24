# BRIEFING — 2026-11-13T04:16:00Z

## Mission
Deep technical investigation into the 16 Agent Tools specified in HANDOFF_PLAN.md across 6 functional groups vs lean code-interpreter / sandbox architectures for DataMate.

## 🔒 My Identity
- Archetype: explorer
- Roles: investigation, synthesis
- Working directory: d:\PROJECT\ZALO-AI-CHALLENGE-2026
- State folder: d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\explorer_survey_1
- Original parent: e8c45a29-5148-4546-ba15-45fed278495a
- Milestone: Investigation 16 Agent Tools vs Lean Code-Interpreter

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Strictly READ-ONLY. Do NOT write or modify code or data files.
- The directory `data/` is strictly read-only. Never modify any files in `data/`.
- Only write metadata/reports in `.agents/teamwork/explorer_survey_1/`.

## Current Parent
- Conversation ID: e8c45a29-5148-4546-ba15-45fed278495a
- Updated: 2026-11-13T04:06:04Z

## Investigation State
- **Explored paths**:
  - `ORIGINAL_REQUEST.md`, `interviewer/prompt_draft.md`, `orchestrator_3/PROJECT.md`
  - `src/agent/solver.py`, `src/agent/sandbox.py`, `src/agent/prompts.py`
  - `src/profiler/business_loader.py`, `src/time_resolver/calendar_utils.py`, `src/postprocess/normalizer.py`
  - `docs/rule.md`, `docs/evaluation.md`, `docs/description.md`
  - `result/r1_pa_diagnosis/prompt_old_vs_current_trace.md`
  - `tests/test_p1_business_loader.py`, `tests/test_p2_solver_guardrails.py`, `tests/test_p3_sandbox_temporal.py`, `tests/test_adversarial_p1_p2_p3.py`, `tests/test_solver_multiturn.py`
- **Key findings**:
  1. `HANDOFF_PLAN.md` is the proposed technical handoff plan outlined in `ORIGINAL_REQUEST.md`.
  2. Dissected 16 tools across 6 functional groups; confirmed 100% duplicate standard Python/Pandas/SQLite functionality.
  3. 16 tool schemas consume 3,200 - 4,000 tokens (20-25% of 16k context window) before any data is loaded.
  4. Multi-turn tool calling triggers turn explosion (8-10 turns vs 1-2 turns), breaching the 43.2s/question budget for 500 private test questions under the 6-hour Docker limit.
  5. Cascading errors over 8-turn tool chains drop probability of success to ~27%, triggering wrong answers and devastating -1.0 PA penalties.
  6. Existing codebase in `src/` already follows the superior Lean Code-Interpreter architecture with deterministic pre-profiling (Step 0) and in-sandbox runtime helpers (`unmerge_and_ffill`, `parse_vn_number`, `parse_vn_date`).
- **Unexplored areas**: None (technical investigation complete).

## Key Decisions Made
- Formulate comprehensive 5-component handoff report proving that the proposed 16 tools represent an anti-pattern for DataMate and recommending strict adherence to the lean Code-Interpreter / Sandbox paradigm.

## Artifact Index
- DISPATCH.md — Received instructions
- BRIEFING.md — Working memory
- progress.md — Heartbeat & status
- handoff.md — Complete technical investigation & critique report
