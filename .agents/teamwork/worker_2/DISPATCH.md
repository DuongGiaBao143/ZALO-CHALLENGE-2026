## 2026-11-12T05:40:10Z
You are a teamwork_worker.
Working directory: d:\PROJECT\ZALO-AI-CHALLENGE-2026
State folder: d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\worker_2
Original request path: d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\ORIGINAL_REQUEST.md
Scope document path: d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\orchestrator_2\SCOPE.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

CRITICAL SAFETY CONSTRAINT:
The directory `data/` is strictly read-only. NEVER write to, modify, rename, or delete any file in `data/`. All test suites and code must run in read-only mode or in RAM.

CONTEXT & INPUTS:
Iteration 1 completed with 83/83 tests passing and a CLEAN forensic audit. The independent Reviewers and Challengers requested 3 specific edge-case fixes:
1. `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\reviewer_2\handoff.md`
2. `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\reviewer_1\handoff.md`
3. `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\challenger_1\handoff.md`
4. `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\orchestrator_2\GATE_STATUS.md`

YOUR TASKS:
1. Fix `src/agent/sandbox.py`:
   - In `unmerge_and_ffill` (both around line 127 in function and around line 597 inside `_SANDBOX_RUNTIME_HELPERS`):
     Change `else:` to `elif not detected_id:`.
     Reason: When a standard unmerged table has complete order IDs, it must NOT execute generic forward-filling across distinct walk-in orders (`None` customer names).
   - In `load_excel_unmerge` (both around line 180 in function and around line 650 inside `_SANDBOX_RUNTIME_HELPERS`):
     Change default parameter `header: Any = 0` (was `header: Any = None`).
     Reason: In pandas, `pd.read_excel()` defaults to `header=0`. Defaulting to `None` converts table columns into integer indices `[0, 1, ...]` and breaks column lookup.
2. Fix `src/agent/solver.py`:
   - In `_eval_guard_issue`:
     - Debt table check (Pattern 2): Parse numeric values safely from strings (e.g. `float(str(r[idx]).replace(',', '').strip()) > 0` if string/number) so tables with formatted positive debt strings (e.g. `'150000'` or `'150,000'`) are recognized as positive debt and not falsely flagged as all-zero.
     - Hallucination Pattern 1 (`[0, 0]`): Also catch string zeros (e.g. `all(str(x).strip() in ('0', '0.0') for x in answer)`) on financial / debt / movement queries.
3. Fix `src/profiler/business_loader.py`:
   - Add `"khachhang"` and `"khach"` to `_EXCLUDED_VALUE_COLUMNS`.
4. Update & Add Tests:
   - In `tests/test_p3_sandbox_temporal.py`: Add `test_unmerge_and_ffill_unmerged_table_no_leakage` (verifying walk-in customer `None` is preserved on unmerged orders) and `test_load_excel_unmerge_default_header` (verifying column headers are string names, not integer 0, 1).
   - In `tests/test_p2_solver_guardrails.py`: Add test verifying formatted string positive debt in debtor tables is accepted, and string zeros `['0', '0']` in debt queries are rejected.
   - Run the complete test suite: `python -m pytest tests/ -v` and verify 100% pass rate.
   - Verify `git status data/` is clean.

OUTPUT:
Write your complete handoff report to:
`d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\worker_2\handoff.md`
Then call send_message to report completion.
