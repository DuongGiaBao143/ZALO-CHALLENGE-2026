# BRIEFING — 2026-11-12T05:40:30Z

## Mission
Implement Iteration 2 reviewer and challenger fixes for sandbox unmerge/header handling, solver guardrails string debt and zero hallucination checks, and business loader column exclusion list, with comprehensive unit tests.

## 🔒 My Identity
- Archetype: teamwork_worker
- Roles: implementer, qa, specialist
- Working directory: d:\PROJECT\ZALO-AI-CHALLENGE-2026
- State folder: d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\worker_2
- Original parent: 0572becd-a423-49d3-aee1-65bcba121c69
- Milestone: iteration_2_fixes

## 🔒 Key Constraints
- The directory `data/` is strictly read-only. NEVER write to, modify, rename, or delete any file in `data/`.
- No dummy/facade implementations or hardcoded test values.
- Write only to state folder `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\worker_2`.
- Minimal changes only.
- 100% test pass rate required.

## Current Parent
- Conversation ID: 0572becd-a423-49d3-aee1-65bcba121c69
- Updated: 2026-11-12T05:40:30Z

## Task Summary
- **What to build**:
  1. `src/agent/sandbox.py`: `unmerge_and_ffill` `elif not detected_id:` and `load_excel_unmerge` `header: Any = 0` (both in module functions and `_SANDBOX_RUNTIME_HELPERS`).
  2. `src/agent/solver.py`: safe string float parsing for positive debt check in Pattern 2, and catch string zeros `('0', '0.0')` in Pattern 1.
  3. `src/profiler/business_loader.py`: add `"khachhang"` and `"khach"` to `_EXCLUDED_VALUE_COLUMNS`.
  4. Tests: update and add tests in `tests/test_p3_sandbox_temporal.py` and `tests/test_p2_solver_guardrails.py`.
- **Success criteria**: All tests passing, genuine implementation, clean data directory git status.
- **Interface contracts**: `PROJECT.md` / `SCOPE.md`

## Key Decisions Made
- Follow reviewer and challenger handoffs precisely.

## Artifact Index
- `.agents/teamwork/worker_2/DISPATCH.md` — Dispatch prompt
- `.agents/teamwork/worker_2/BRIEFING.md` — Agent state and briefing
- `.agents/teamwork/worker_2/progress.md` — Execution progress heartbeat
- `.agents/teamwork/worker_2/handoff.md` — Handoff report

## Change Tracker
- **Files modified**: None yet
- **Build status**: Pending
- **Pending issues**: None

## Quality Status
- **Build/test result**: Not run yet
- **Lint status**: Clean
- **Tests added/modified**: Pending

## Loaded Skills
- None
