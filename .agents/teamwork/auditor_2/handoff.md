# Forensic Audit Report — Iteration 2 Work Products (worker_3)

**Work Product**: Iteration 2 implementations in `src/agent/sandbox.py`, `src/agent/solver.py`, `src/profiler/business_loader.py`, `tests/test_p3_sandbox_temporal.py`, `tests/test_p2_solver_guardrails.py`  
**Profile**: General Project  
**Integrity Mode**: Demo (inferred directly from `ORIGINAL_REQUEST.md`)  
**Verdict**: **CLEAN**  

---

## 1. Observation

1. **Static Analysis & Pattern Scan**:
   - Files scanned: `src/agent/sandbox.py`, `src/agent/solver.py`, `src/profiler/business_loader.py`, `tests/test_p3_sandbox_temporal.py`, `tests/test_p2_solver_guardrails.py`.
   - Tool Command:
     ```python
     qid_pattern = re.compile(r'(dev_\d{3}_q\d{3}|biz_\d{3}_q\d{3})', re.IGNORECASE)
     ```
   - Verbatim Output:
     ```text
     src/agent/sandbox.py: NO hardcoded question IDs found.
     src/agent/solver.py: NO hardcoded question IDs found.
     src/profiler/business_loader.py: NO hardcoded question IDs found.
     tests/test_p3_sandbox_temporal.py: NO hardcoded question IDs found.
     tests/test_p2_solver_guardrails.py: NO hardcoded question IDs found.
     ```
   - AST Inspection: Scanned all function definitions across all touched files for dummy implementations (pass-only or returning fixed constants).
     Verbatim Output:
     ```text
     AST scan completed. (0 pass-only functions, 0 dummy return-constant functions)
     ```

2. **Runtime Tracing & Genuine Computation Verification**:
   - **`unmerge_and_ffill` `elif not detected_id:`**:
     Lines 125-136 & Lines 595-602 in `src/agent/sandbox.py`:
     ```python
         order_group = df[detected_id].notna().cumsum()
         df[cols_to_fill] = df.groupby(order_group)[cols_to_fill].ffill()
     elif not detected_id:
         # Fallback for generic parent columns if no explicit ID column
         parent_keywords = ['ma don', 'ngay dat', 'ngay lap', 'trang thai', 'ten khach']
         generic_cols = [
             c for c, norm_c in norm_col_map.items()
             if any(k in norm_c for k in parent_keywords) and df[c].isna().any()
         ]
         if generic_cols:
             df[generic_cols] = df[generic_cols].ffill()
     ```
     Empirical test executed:
     ```powershell
     python -c "import pandas as pd; from src.agent.sandbox import unmerge_and_ffill; df = pd.DataFrame({'Mã đơn': ['DH1', 'DH2', 'DH3'], 'Tên khách': ['Nguyễn Văn A', None, None]}); res = unmerge_and_ffill(df); assert res.loc[0, 'Tên khách'] == 'Nguyễn Văn A'; assert pd.isna(res.loc[1, 'Tên khách']); assert pd.isna(res.loc[2, 'Tên khách']); print('Leakage test passed!')"
     ```
     Verbatim Output: `Leakage test passed!` (Exit code: 0).
     When `detected_id` exists and is complete (unmerged flat orders), the generic fallback is skipped, preventing customer leakage to subsequent walk-in customers.

   - **`load_excel_unmerge` `header: Any = 0` default**:
     Lines 153-167 & Lines 615-621 in `src/agent/sandbox.py`:
     `header: Any = 0` is explicitly set as the default parameter, matching `pd.read_excel` semantics.
     Empirical test `tests/test_p3_sandbox_temporal.py::test_load_excel_unmerge_default_header` passed: verified string column names (`'Mã đơn'`, `'Tên khách'`, `'Tiền'`) are preserved.

   - **Safe Numeric String Parsing (`_is_positive_num`, `_is_zero_val`)**:
     Lines 729-742 & Lines 758-771 in `src/agent/solver.py`:
     Empirical test script tested numbers, zero strings (`"0"`, `"0.0"`, `"0,0"`, `" 0 "`), positive debt strings (`"150000"`, `"150,000"`, `"150.000"`, `"150.000,50"`), negative values, and non-numeric strings.
     Verbatim Output: `All _is_zero_val and _is_positive_num tests passed!` (Exit code: 0).

3. **Test Suite Integrity & Execution**:
   - **`tests/test_p3_sandbox_temporal.py` (11 tests)**:
     Command: `python -m pytest tests/test_p3_sandbox_temporal.py -v`
     Verbatim Output: `11 passed in 28.81s` (Exit code: 0).
   - **`tests/test_p2_solver_guardrails.py` (11 tests)**:
     Command: `python -m pytest tests/test_p2_solver_guardrails.py -v`
     Verbatim Output: `11 passed in 1.13s` (Exit code: 0).
   - **`tests/test_p1_business_loader.py` & `tests/test_dev_regression.py` (11 tests)**:
     Command: `python -m pytest tests/test_p1_business_loader.py tests/test_dev_regression.py -v`
     Verbatim Output: `11 passed in 35.70s` (Exit code: 0).
   - **`tests/test_adversarial_p1_p2_p3.py` & `tests/test_empirical_challenger.py` (21 tests)**:
     Command: `python -m pytest tests/test_adversarial_p1_p2_p3.py tests/test_empirical_challenger.py -v`
     Verbatim Output: `21 passed in 32.84s` (Exit code: 0).
   - **Full Core DataMate Test Suite (130 items)**:
     Command: `python -m pytest tests/test_p1_business_loader.py tests/test_p2_solver_guardrails.py tests/test_p3_sandbox_temporal.py tests/test_dev_regression.py tests/test_adversarial_p1_p2_p3.py tests/test_empirical_challenger.py tests/test_profiler.py tests/test_codex_profiler_review.py tests/test_sandbox_protocol.py tests/test_time_resolver.py tests/test_solver_multiturn.py tests/test_codex_solver_review.py tests/test_codex_runtime_review.py tests/test_prompt_context.py tests/test_eval_and_normalizer.py -v`
     Verbatim Output: `130 passed in 134.41s (0:02:14)` (Exit code: 0).

4. **Data Immutability Verification**:
   - Command: `git status data/`
   - Verbatim Output:
     ```text
     On branch giabao
     Your branch is up to date with 'origin/giabao'.

     nothing to commit, working tree clean
     ```
   - Command: `git status result/`
   - Verbatim Output: `nothing to commit, working tree clean`.
   - Result: Raw data in `data/` is 100% clean, unmodified, and preserved. No fabricated verification output exists in `result/`.

---

## 2. Logic Chain

1. **Integrity Mode Derivation**:
   - `ORIGINAL_REQUEST.md` specifies `Integrity mode: demo` with constraints:
     - No external network/API calls.
     - Model parameter count $\le 15\text{B}$.
     - Raw data in `data/` strictly read-only.
     - No reading test sources to hardcode answers.
2. **Static Forensics**:
   - All touched files were evaluated against prohibited patterns (hardcoded test results, facade implementations, pre-populated result artifacts, self-certifying tests, external delegation).
   - Regex and AST parsing confirm zero question ID matches, zero hardcoded answer dictionaries, and zero dummy/pass-only implementations (Observation 1).
3. **Behavioral Forensics**:
   - Code changes in `sandbox.py`, `solver.py`, and `business_loader.py` implement genuine algorithmic logic addressing the edge cases identified in Iteration 1 review.
   - Empirical evaluation confirms:
     - `unmerge_and_ffill` distinguishes between merged child rows (where `detected_id.isna()`) and unmerged separate orders (where `detected_id.notna()`), preventing customer name propagation across separate orders (Observation 2).
     - `load_excel_unmerge` retains string headers by default, preventing `RangeIndex` column errors (Observation 2).
     - `_eval_guard_issue` safely parses Vietnamese number formats with period and comma separators, eliminating false rejections of valid debt tables while catching all variations of all-zero lists (Observation 2).
4. **Test Integrity**:
   - Test suites in `tests/test_p3_sandbox_temporal.py` and `tests/test_p2_solver_guardrails.py` contain non-vacuous, boundary-testing assertions that verify both acceptance and rejection conditions.
   - All 130 tests across all core modules pass natively in offline environment (Observation 3).
5. **Data Immutability**:
   - `git status data/` and `git status result/` confirm zero changes to competition data or output trees (Observation 4).
6. **Verdict Deduction**:
   - Every forensic check passed with concrete tool evidence.
   - Under Demo Mode rules, no integrity violations exist. The final verdict is **CLEAN**.

---

## 3. Caveats

- **Scope Boundary**: Audit focused on Iteration 2 work products and edge-case fixes implemented by worker_3. Out-of-tree deprecated SFT notebooks (`tests/test_colab_eval_prompt_notebook.py`, `tests/test_kaggle_sft_208.py`) reference notebook files removed in earlier repository cleanups and were not part of this milestone.
- **Hardware Profile**: All unit and integration tests were executed on local CPU. GPU-specific vLLM memory limits are bounded by config (`tensor_parallel_size`, `gpu_memory_utilization`, `max_model_len: 16384`) conforming to the 2x RTX 5090 competition constraint.

---

## 4. Conclusion

The work products delivered by `worker_3` for Iteration 2 pass all forensic integrity checks:
- **Verdict**: **`CLEAN`**
- **Hardcoded Results / Cheating**: None found (0 matches).
- **Implementation Authenticity**: All functions implement genuine, verifiable computation.
- **Test Integrity**: Independent test suites contain real, non-vacuous assertions and pass 100% (130/130 core tests passed).
- **Data Immutability**: `data/` is 100% untouched and pristine.
- **Recommendation**: Accept work product for final merge and iteration sign-off.

---

## 5. Verification Method

To independently reproduce and verify this audit:

1. **Verify Data Immutability**:
   ```powershell
   git status data/
   ```
   *Expected output*: `nothing to commit, working tree clean`.

2. **Verify AST and Question ID Scans**:
   ```powershell
   python -c "import re; [print(f, 'CLEAN') for f in ['src/agent/sandbox.py', 'src/agent/solver.py', 'src/profiler/business_loader.py', 'tests/test_p3_sandbox_temporal.py', 'tests/test_p2_solver_guardrails.py'] if not re.findall(r'(dev_\d{3}_q\d{3}|biz_\d{3}_q\d{3})', open(f, encoding='utf-8').read())]"
   ```

3. **Verify Direct Unmerge Leakage Prevention**:
   ```powershell
   python -c "import pandas as pd; from src.agent.sandbox import unmerge_and_ffill; df = pd.DataFrame({'Mã đơn': ['DH1', 'DH2', 'DH3'], 'Tên khách': ['Nguyễn Văn A', None, None]}); res = unmerge_and_ffill(df); assert res.loc[0, 'Tên khách'] == 'Nguyễn Văn A'; assert pd.isna(res.loc[1, 'Tên khách']); assert pd.isna(res.loc[2, 'Tên khách']); print('Leakage test passed!')"
   ```

4. **Run Full 130 Core Tests**:
   ```powershell
   python -m pytest tests/test_p1_business_loader.py tests/test_p2_solver_guardrails.py tests/test_p3_sandbox_temporal.py tests/test_dev_regression.py tests/test_adversarial_p1_p2_p3.py tests/test_empirical_challenger.py tests/test_profiler.py tests/test_codex_profiler_review.py tests/test_sandbox_protocol.py tests/test_time_resolver.py tests/test_solver_multiturn.py tests/test_codex_solver_review.py tests/test_codex_runtime_review.py tests/test_prompt_context.py tests/test_eval_and_normalizer.py -v
   ```
   *Expected output*: `130 passed`.
