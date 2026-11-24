# Hard Handoff Report — DataMate P1, P2, P3 Hardening & Verification Complete

**Author**: Orchestrator 2 (`orchestrator_2`)  
**Parent Agent**: `4025361d-eada-4198-adde-f0436a3b8a4f`  
**Milestone**: Complete P1, P2, P3 Hardening, Adversarial Verification & Gate PASS  
**Date**: 2026-11-12T06:28:00Z  
**Status**: Completed (Hard Handoff — GATE PASS CONFIRMED)  

---

## 1. Observation

### 1.1 Requirements Met
1. **R1 (P1 — `business_loader.py` Schema Profiling & Context Capping)**:
   - Full in-memory RAM scanning: removed `_PREFLIGHT_ROWS = 200` row limit. Data profiling scans complete DataFrames and SQLite tables, computing exact `unique_count`.
   - Clear classification: columns with cardinality $\le 20$ are classified as `[TOÀN BỘ NHÃN / ALL LABELS (unique=N)]` (ordered by frequency), while columns with $> 20$ are classified as `[MẪU THAM KHẢO / SAMPLE VALUES (top tần suất, unique=N)]`.
   - Masked PII: columns like `Tên khách hàng`, `Khách hàng`, `CCCD`, `SĐT`, `Địa chỉ` are strictly excluded from categorical sample dumping.
   - Sheet deduplication: identical-schema sheets across workbooks are consolidated into single declarations (`consolidate_workbook_sheets`).
   - Context window capping: enforced `MAX_SCHEMA_CHARS = 7000` with graceful two-stage fallback (first dropping sample values, then cleanly truncating) to prevent 16k context window exhaustion.

2. **R2 (P2 — `solver.py` Step 3 Core Rules, Zero Handling & Abstain Gate)**:
   - Activated `eval_core_rules = True` by default in solver and configuration.
   - Decoupled `metadata_only` from `eval_core_rules` so P1 full RAM scan operates without restriction.
   - Verified zero acceptance: allows `0` when supported by valid sandbox filter checks (`rows_after_filter > 0` or verified status), while rejecting unverified/hallucinated zeros.
   - Hallucination blockers: intercepts and blocks `[0, 0]` lists, all-zero debt tables, and unaggregated duplicate top-k ranking lists.
   - Abstain Gate: wrapped `answer_question_with_trace` in top-level `try ... except Exception` block falling back to `SubmissionItem.abstain(...)` on unhandled errors, and set `abstain_on_unanswerable = True` by default to eliminate $-1.0$ PA penalties.

3. **R3 (P3 — `sandbox.py` Excel Unmerge & `calendar_utils.py` Temporal Resolution)**:
   - Added `unmerge_and_ffill`, `load_excel_unmerge`, and `unmerge_openpyxl_sheet` to sandbox runtime.
   - Fixed unmerge forward-fill to use `order_group = df[detected_id].notna().cumsum()` and `elif not detected_id:` to prevent cross-order leakage to walk-in customers (`None`).
   - Fixed `load_excel_unmerge` default parameter to `header: Any = 0`.
   - In `calendar_utils.py` and `prompts.py`, added exact resolution for `"cùng kỳ tháng trước"` with leap-year clamping and prompt regex matching that injects same-period intervals while suppressing misleading full-month intervals.

4. **R4 (Data Safety & Compliance)**:
   - Directory `data/` is 100% clean, pristine, and untouched (`git status data/` clean).
   - Solution operates 100% offline (`--network none`) and complies with $\le 15\text{B}$ model budget.

### 1.2 Verification & Test Results
- **Pytest Full Core Suite**: **144 tests passed in 137.88s (0 failures, 0 regressions)**.
- **Forensic Integrity Audit**: **CLEAN** (Auditor 1 and Auditor 2 confirmed 0 hardcoded question IDs, 0 hardcoded answers, 0 dummy facades, and genuine algorithms).
- **Adversarial Stress Tests**: All 14 stress tests in `tests/test_challenger_iteration2_stress.py` passed in 2.99s.
- **Dev Failure Cases Replay**: Confirmed PA score improvement on dev failure cases from $-1.000$ to $+0.400$ ($+1.400$ net delta).

---

## 2. Logic Chain

1. In baseline evaluation, the pipeline suffered a $-0.5000$ PA score due to:
   - Status label mismatch (`.str.contains("hoàn thành")` on `Xong` / `completed`) caused by profiler 200-row sampling.
   - Excel merged cells leaving 47% child rows `NaN` in `biz_121` and `biz_122`.
   - Prompt misguidance on "cùng kỳ tháng trước" comparing 3 days against 30 days.
   - Hallucinated `[0, 0]` debt lists, duplicate top-k products, and crashes.
2. Step 1 (P1) full RAM profiling exposes 100% of real status labels (`Xong`, `completed`, `returned`, `cancelled`) in the schema, eliminating empty-filter bugs at the root. Context capping guarantees $< 7000$ chars, fitting comfortably in the 16k context window.
3. Step 2 (P3) sandbox unmerge helper recovers parent attributes on child item lines, allowing correct order filtering and matching gold amounts (e.g. 248,572,900 VND on `biz_122`). Temporal resolver accurately binds same-period intervals and suppresses full-month intervals.
4. Step 3 (P2) solver guardrails intercept any remaining edge cases (`[0, 0]`, zero-debt tables, duplicate rankings, unverified zeros) and cleanly route unresolvable failures to `abstain` ($0.0$ pts instead of $-1.0$ penalty).
5. Reviewer and Challenger adversarial stress testing caught 3 edge cases in Iteration 1 (walk-in customer leakage, default header=0, formatted debt string parsing), all of which were resolved in Iteration 2 and verified with 144 passing tests.
6. The Forensic Auditor verified the absence of cheating or hardcoding, confirming the integrity of the solution.

---

## 3. Caveats

- All tests and benchmarks run locally in strictly offline mode (`--network none`).
- Hardware requirements (2x RTX 5090, CUDA $\ge 12.8$) and $\le 15\text{B}$ open-weights model limits are fully respected.
- `data/` directory remained 100% read-only throughout all iterations.

---

## 4. Conclusion

- **Gate Result: PASS** across all evaluation criteria.
- Reviewer 3: `APPROVE`
- Reviewer 4: `APPROVE`
- Challenger 3: `APPROVE`
- Forensic Auditor 2: `CLEAN`
- Deliverables are ready for official competition deployment.

---

## 5. Verification Method

To independently verify the complete deliverables:

1. **Run Full Automated Core Test Suite**:
   ```powershell
   python -m pytest tests/test_p1_business_loader.py tests/test_p2_solver_guardrails.py tests/test_p3_sandbox_temporal.py tests/test_dev_regression.py tests/test_adversarial_p1_p2_p3.py tests/test_challenger_iteration2_stress.py tests/test_empirical_challenger.py tests/test_profiler.py tests/test_codex_profiler_review.py tests/test_sandbox_protocol.py tests/test_time_resolver.py tests/test_solver_multiturn.py tests/test_codex_solver_review.py tests/test_codex_runtime_review.py tests/test_prompt_context.py tests/test_eval_and_normalizer.py -v
   ```
   *Expected Outcome*: `144 passed in ~138s`.

2. **Verify Walk-in Customer Protection & Header Default**:
   ```powershell
   python -m pytest tests/test_p3_sandbox_temporal.py -k "test_unmerge_and_ffill_unmerged_table_no_leakage or test_load_excel_unmerge_default_header" -v
   ```
   *Expected Outcome*: `2 passed`.

3. **Verify Solver Guardrails**:
   ```powershell
   python -m pytest tests/test_p2_solver_guardrails.py -k "test_debt_table_with_formatted_string_positive_debt_accepted or test_hallucination_string_zeros_list_blocked" -v
   ```
   *Expected Outcome*: `2 passed`.

4. **Verify Raw Data Immutability**:
   ```powershell
   git status data/
   ```
   *Expected Outcome*: `nothing to commit, working tree clean`.
