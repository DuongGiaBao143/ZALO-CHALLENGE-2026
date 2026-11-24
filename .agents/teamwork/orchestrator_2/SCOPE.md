# Scope: DataMate P1, P2, P3 Pipeline Enhancements

## Architecture & Code Layout
- Modified source files:
  1. `src/schemas.py`: Add `column_unique_counts` and `exhaustive_columns` to `TableSchema`.
  2. `src/profiler/business_loader.py`: Full in-memory RAM scanning, exact `unique_count`, exhaustive labels vs sample values, context capping (≤7000 chars), sheet deduplication.
  3. `src/agent/sandbox.py`: `unmerge_and_ffill`, `load_excel_unmerge`, `unmerge_openpyxl_sheet`, and inject into `_SANDBOX_RUNTIME_HELPERS` & `_smart_read_excel`.
  4. `src/time_resolver/calendar_utils.py`: Add "cùng kỳ tháng trước" date interval resolution with leap-year clamping.
  5. `src/agent/prompts.py`: Fix regex in `build_user_prompt` for "cùng kỳ tháng trước" (suppress full month, inject same-period interval); add helper notes in `BASE_SYSTEM_PROMPT`.
  6. `src/agent/solver.py`: Enable `eval_core_rules = True` by default; decouple `metadata_only`; verified zero acceptance check; hallucination blockers (`[0, 0]`, zero-debt tables, duplicate top-k ranking); Abstain Gate fallback on unhandled exceptions and retry exhaustion; `abstain_on_unanswerable = True`.
- New independent unit and regression test files:
  7. `tests/test_p1_business_loader.py`: RAM scan, label/sample separation, context capping, sheet grouping.
  8. `tests/test_p3_sandbox_temporal.py`: Excel unmerge/ffill, sandbox globals, "cùng kỳ tháng trước" resolution & prompt injection.
  9. `tests/test_p2_solver_guardrails.py`: Core rules active, zero verification check, hallucination blockers, safe abstain fallback.
  10. `tests/test_dev_regression.py`: Regression verification against dev cases from `failure_analysis.md`.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Full RAM scan for low-cardinality columns | Remove 200-row limit for categorical profiling, report exact unique_count | M1 (P1) | R1 |
| 2 | Separation of exhaustive labels vs reference samples | Full labels for low unique vs annotated sample for high unique | M1 (P1) | R1 |
| 3 | Context capping for schema block (16k window) | Hard cap on labels and block size (≤7000 chars), top frequency for dirty columns | M1 (P1) | R1 |
| 4 | Identical schema sheet grouping | Deduplicate and group identical schema sheets | M1 (P1) | R1 |
| 5 | Sandbox Excel unmerge & ffill helper | Vectorized ffill and openpyxl unmerge in sandbox runtime | M2 (P3) | R3 |
| 6 | Relative temporal resolution "cùng kỳ tháng trước" | Parse and resolve "cùng kỳ tháng trước" in calendar_utils and prompts | M2 (P3) | R3 |
| 7 | Activate eval_core_rules in Step 3 | Enable rule evaluation flag and execution guardrails by default | M3 (P2) | R2 |
| 8 | Verified zero result acceptance | Accept 0 when backed by valid sandbox check, reject unverified 0 | M3 (P2) | R2 |
| 9 | Hallucination pattern blocker | Detect & reject [0,0], zero-debt tables, duplicate top-k ranking | M3 (P2) | R2 |
| 10| Abstain Gate fallback on retry exhaustion | Fallback cleanly to "abstain" when execution fails or retry limit reached | M3 (P2) | R2 |
| 11| Independent automated unit test suite | Comprehensive tests for P1, P2, P3 under tests/ | M4 (Verify) | Acceptance Criteria |
| 12| Regression verification on failure_analysis.md | Validate improvements on failing dev questions without regression | M4 (Verify) | Acceptance Criteria |

## Implementation Ownership
- Worker `worker_1` owns:
  - `src/schemas.py`
  - `src/profiler/business_loader.py`
  - `src/agent/sandbox.py`
  - `src/time_resolver/calendar_utils.py`
  - `src/agent/prompts.py`
  - `src/agent/solver.py`
  - `tests/test_p1_business_loader.py`
  - `tests/test_p3_sandbox_temporal.py`
  - `tests/test_p2_solver_guardrails.py`
  - `tests/test_dev_regression.py`
- All other files (especially `data/`) are strictly read-only.


## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: P1 Schema Profiling & Context Capping | `src/profiler/business_loader.py`, `src/schemas.py` | None | DONE |
| 2 | M2: P3 Sandbox Unmerge & Temporal Resolution | `src/agent/sandbox.py`, `src/time_resolver/calendar_utils.py`, `src/agent/prompts.py` | None | DONE |
| 3 | M3: P2 Solver Core Rules, Zero Handling & Abstain Gate | `src/agent/solver.py` | M1, M2 | DONE |
| 4 | M4: Testing, Verification & Regression Validation | `tests/`, verification runner | M1, M2, M3 | DONE |

## Gate Verdict
- Iteration 1: FAIL (Targeted edge cases identified by Reviewers & Challenger)
- Iteration 2: **PASS** (Reviewer 3: APPROVE, Reviewer 4: APPROVE, Challenger 3: APPROVE, Forensic Auditor 2: CLEAN)
- Final Test Count: 144 passed, 0 failed.
- Data Integrity: 100% clean, pristine, 0 changes in `data/`.
