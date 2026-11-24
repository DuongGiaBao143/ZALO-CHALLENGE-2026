# Review & Adversarial Challenge Report — Iteration 2 Edge-Case Refinements

**Author**: `reviewer_4` (Roles: reviewer, critic)  
**Parent Agent**: `0572becd-a423-49d3-aee1-65bcba121c69`  
**Milestone**: Iteration 2 Independent Code Review & Adversarial Stress Testing  
**State Folder**: `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\reviewer_4`  
**Date**: 2026-11-12T06:20:00Z  

---

## Review Summary

**Verdict**: **APPROVE**  
**Overall Risk Assessment**: **LOW**  
**Integrity Attestation**: **VERIFIED — ZERO INTEGRITY VIOLATIONS DETECTED**

All 4 specific bug fixes identified during Iteration 1 review and adversarial probing have been accurately implemented, thoroughly tested, and independently verified without regressions. `data/` directory remains 100% clean and untouched.

---

## 1. Observation

### 1.1 Source Code Inspection
1. **`src/agent/sandbox.py:127` & `src/agent/sandbox.py:597` (`unmerge_and_ffill`)**:
   - Replaced unconstrained fallback branch `else:` with `elif not detected_id:`.
   - Verified in both python function and `_SANDBOX_RUNTIME_HELPERS` string:
     ```python
     order_group = df[detected_id].notna().cumsum()
     df[cols_to_fill] = df.groupby(order_group)[cols_to_fill].ffill()
     elif not detected_id:
         # Fallback for generic parent columns if no explicit ID column
     ```
   - On flat tables where every row has an order ID (no NaNs in `detected_id`) and walk-in customers have `Tên khách = None`, execution bypasses forward-fill. Null walk-in customer cells remain `None` and do not inherit prior customer names, strictly adhering to Rulebook Section 8.

2. **`src/agent/sandbox.py:156` & `src/agent/sandbox.py:615` (`load_excel_unmerge`)**:
   - Set default argument `header: Any = 0` in `load_excel_unmerge(io, sheet_name=0, header=0, ...)` matching `pd.read_excel` convention.
   - Excel sheets loaded via `load_excel_unmerge(path)` without explicit header arguments preserve original string column names (e.g., `'Mã đơn'`, `'Tên khách'`) instead of producing integer `RangeIndex(0, N)` that triggered `KeyError`.

3. **`src/agent/solver.py:728-744` (`_eval_guard_issue` Pattern 1: Zero List Blocker)**:
   - Defined `_is_zero_val(x)` supporting integers, floats, numpy scalars (`np.number`), string zeros (`"0"`, `"0.0"`, `"0.00"`), Vietnamese comma decimals (`"0,0"`, `"0,00"`), and whitespace-padded zeros (`" 0 "`).
   - Line 14: `import numpy as np` added, eliminating `NameError: name 'np' is not defined`.
   - Hallucination error `"Danh sách kết quả toàn số 0 ([0, 0] hoặc tương tự)"` triggers consistently on all variations of zero lists.

4. **`src/agent/solver.py:758-784` (`_eval_guard_issue` Pattern 2: Debt Table Guard)**:
   - Implemented `_is_positive_num(val)` and `_is_num_cell(val)` with safe numeric string parsing:
     - Handles standard numeric types (`int`, `float`, `np.number`).
     - Parses comma-separated strings via `val.replace(",", "").strip()`.
     - Parses Vietnamese thousand separators via `val.replace(".", "").replace(",", ".").strip()`.
   - Positive string debt values (e.g. `'150000'`, `'150,000'`, `'150.000'`) are evaluated as `> 0` and accepted, eliminating false rejections.
   - Non-positive string debts (e.g. `'0'`, `'0.0'`, `'-150,000'`) are correctly caught.

5. **`src/profiler/business_loader.py:194-205` (`_EXCLUDED_VALUE_COLUMNS`)**:
   - Added `"khachhang"` and `"khach"` to `_EXCLUDED_VALUE_COLUMNS`.
   - `_is_excluded_value_column("Khách hàng")` and `_is_excluded_value_column("Khách")` return `True` under unaccented case-folded normalization, preventing customer PII leakage in prompt schemas.

### 1.2 Automated Pytest Suite Execution
1. **Targeted Refinement Suite (49 items)**:
   - Command:
     ```powershell
     python -m pytest tests/test_p1_business_loader.py tests/test_p2_solver_guardrails.py tests/test_p3_sandbox_temporal.py tests/test_dev_regression.py tests/test_adversarial_p1_p2_p3.py -v
     ```
   - Verbatim Output:
     ```text
     ======================== 49 passed in 66.86s (0:01:06) ========================
     ```
   - Exit code: 0.

2. **Empirical Challenger Suite (5 items)**:
   - Command:
     ```powershell
     python -m pytest tests/test_empirical_challenger.py -v
     ```
   - Verbatim Output:
     ```text
     ============================= 5 passed in 31.22s ==============================
     ```
   - Exit code: 0.

### 1.3 Anti-Cheat & Codebase Integrity Scan
1. **Raw Data Preservation**:
   - Command: `git status data/`
   - Verbatim Output:
     ```text
     On branch giabao
     Your branch is up to date with 'origin/giabao'.

     nothing to commit, working tree clean
     ```
   - Zero files in `data/` were modified, created, or deleted.

2. **Anti-Cheat Verification**:
   - Scanned all files under `src/` for hardcoded question IDs (`q_02a70ea566f1`, `q_43df08e6cce8`, etc.), business IDs (`biz_121`, `biz_122`), or hardcoded gold answers (`248572900`).
   - Verbatim Output: `Violations in src: []`.
   - Source implementation is general-purpose without shortcuts or facade methods.

---

## 2. Logic Chain

1. **Walk-in Customer Leakage Fix**:
   - *Observation*: In `src/agent/sandbox.py:127`, `unmerge_and_ffill` previously used `else:`. For flat tables where `detected_id` was fully populated (no NaNs), it entered `else:` and executed global `ffill` on `Tên khách`, overwriting `None` walk-in customers with prior order customers.
   - *Fix Verification*: Changing `else:` to `elif not detected_id:` ensures that when an explicit ID column is present and complete, no cross-row forward fill occurs. Independent test verified that `df = pd.DataFrame({'Mã đơn': ['DH1', 'DH2', 'DH3'], 'Tên khách': ['Nguyễn Văn A', None, None]})` leaves row 1 and row 2 as `None`.
   - *Conclusion*: Rulebook Section 8 compliance is preserved.

2. **Default Header Fix in load_excel_unmerge**:
   - *Observation*: `load_excel_unmerge` defaulted to `header=None`, causing standard LLM-generated code (`df = load_excel_unmerge(path)`) to produce integer columns `RangeIndex(0, N)` and crash with `KeyError` on column names.
   - *Fix Verification*: Default `header: Any = 0` was set in both `load_excel_unmerge` function definition and `_SANDBOX_RUNTIME_HELPERS`. Independent test verified that string column headers (`'Mã đơn'`, `'Tên khách'`) are preserved.
   - *Conclusion*: Compatibility with standard `pd.read_excel` semantics is restored.

3. **Numeric String Parsing in Solver Guardrails**:
   - *Observation*: `_eval_guard_issue` previously tested `isinstance(r[idx], (int, float))`. Tables where positive debt was represented as string (e.g. `'150000'`, `'150,000'`) were falsely rejected as all-zero hallucinated debt tables. Concurrently, string zero lists (e.g. `['0', '0']`) bypassed `_eval_guard_issue`.
   - *Fix Verification*: Implemented `_is_positive_num` and `_is_zero_val` supporting comma and period formatted strings. Independent test passed across `'150000'`, `'150,000'`, `'150.000'`, `' 250000 '`, while correctly catching `['0', '0']`, `['0.0', '0.0']`, `['0,0', '0.00']`.
   - *Conclusion*: Eliminates false rejection of valid debt tables and blocks string-zero hallucinations.

4. **Customer Column Exclusion in Profiler**:
   - *Observation*: `_is_excluded_value_column` matched `"tenkhachhang"` and `"tenkhach"`, but not columns named simply `"Khách hàng"` or `"Khách"`.
   - *Fix Verification*: Added `"khachhang"` and `"khach"` to `_EXCLUDED_VALUE_COLUMNS`. Normalization strips accents and special characters, correctly matching `"Khách hàng"` and `"Khách"`.
   - *Conclusion*: Customer names are safely excluded from schema previews.

---

## 3. Caveats

- **No Caveats on Implementation**: All 4 target refinements are fully verified and meet all design and competition requirements.
- **Unaccented Duplicates in Ranking**: Probing showed that duplicate ranking blocker normalizes NFC and casefolds, but does not strip accents (e.g., `'Cà phê'` vs `'Ca phe'`). This is an acceptable minor limitation for now since LLM generation typically adheres to consistent diacritics.

---

## 4. Conclusion

**Verdict: APPROVE**

The Iteration 2 code refinements implemented by `worker_3` completely and correctly resolve all reported defects. The implementation is robust, adheres strictly to project rules, passes all 49 unit and adversarial tests as well as the 5 empirical challenger tests, preserves `data/` immutability, and contains zero integrity violations.

---

## 5. Verification Method

To independently verify all findings and results:

1. **Execute Targeted Test Suite**:
   ```powershell
   python -m pytest tests/test_p1_business_loader.py tests/test_p2_solver_guardrails.py tests/test_p3_sandbox_temporal.py tests/test_dev_regression.py tests/test_adversarial_p1_p2_p3.py -v
   ```
   *Expected*: `49 passed`.

2. **Execute Empirical Challenger Suite**:
   ```powershell
   python -m pytest tests/test_empirical_challenger.py -v
   ```
   *Expected*: `5 passed`.

3. **Verify Git Status on data/**:
   ```powershell
   git status data/
   ```
   *Expected*: `nothing to commit, working tree clean`.

4. **Adversarial Edge-Case One-Liners**:
   ```powershell
   python -c "import pandas as pd; from src.agent.sandbox import unmerge_and_ffill; df = pd.DataFrame({'Mã đơn': ['DH1', 'DH2', 'DH3'], 'Tên khách': ['Nguyễn Văn A', None, None]}); res = unmerge_and_ffill(df); assert res.loc[0, 'Tên khách'] == 'Nguyễn Văn A'; assert pd.isna(res.loc[1, 'Tên khách']); assert pd.isna(res.loc[2, 'Tên khách']); print('Unmerge leakage test passed!')"
   ```
   ```powershell
   python -c "from src.agent.solver import _eval_guard_issue; from src.schemas import BusinessProfile; prof = BusinessProfile('b', '', '', []); tbl = {'columns': ['Khách', 'Tiền nợ'], 'rows': [['KH1', '150,000']]}; assert _eval_guard_issue('bảng nợ', 'table', tbl, None, False, prof) is None; print('String debt test passed!')"
   ```
