# HANDOFF REPORT — ARCHITECTURAL CRITIQUE & TECHNICAL RISK ASSESSMENT (R3 & R4)

- **Agent**: teamwork_critic
- **Role**: Critic / Reviewer / Specialist
- **Task**: Architectural Critique and Technical Risk Assessment for Zalo AI Challenge 2026: DataMate
- **Target Report**: `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\critic_1\analysis.md`
- **Date**: 2026-11-11

---

## 1. OBSERVATION

1. **Failure Analysis Baseline**:
   - File: `result/qwen25_14b_1m_code_only_rulebook_20261111_155610/eval_dev_30_colab_a100_40gb_ctx16384/failure_analysis.md` (lines 3, 9, 10, 39, 49):
     - Score: 4 correct, 19 wrong, 7 abstain, $\text{PA} = -0.5000$.
     - "Lọc trạng thái theo chữ 'hoàn thành' làm rỗng dữ liệu... biz_101 có nhãn Xong, còn biz_111, biz_127 và biz_129 dùng completed. Bộ lọc trả 0 dòng ở cả 7 câu."
     - "Sheet tháng 9 của biz_122 có 2.654/5.635 dòng trống mã đơn, ngày và trạng thái... File của biz_121 cũng có 38.878/82.920 dòng thiếu ba trường cấp đơn." (47% data loss due to merged cells).
     - "12/19 câu sai chốt ngay lượt đầu. Sandbox chấp nhận script thực thi và JSON hợp lệ."
     - "Join hai bảng cùng có Tên hàng, pandas thêm hậu tố. Code vẫn group theo tên cột cũ và lặp lại cùng lỗi cả 3 lượt."
2. **Competition Rules & Constraints**:
   - File: `docs/rule.md` (lines 20-22, 25-28, 41-45, 47-52):
     - Max model parameters: $\le 15\text{B}$.
     - Offline Docker (`--network none`).
     - Reference Hardware: 2x NVIDIA RTX 5090 (32GB VRAM each = 64GB VRAM total), 512GB host RAM, CUDA $\ge 12.8$.
     - Wall-clock time limit: 6 hours (21,600s) for ~500 private test questions.
     - Reproducibility threshold: $|\text{PA}_{\text{uploaded}} - \text{PA}_{\text{rerun}}| \le 0.03$ or disqualified.
   - File: `docs/evaluation.md` (lines 31-39):
     - Penalized Accuracy: $\text{PA} = \frac{1}{N} \sum s_i$, where $s_i \in \{+1.0, 0.0, -1.0\}$.
     - Tie-breaker: "thứ hạng sẽ được phân định ưu tiên theo TỔNG THỜI GIAN SUY LUẬN (total inference time)".
3. **Current Agent Codebase**:
   - File: `src/agent/solver.py` (lines 238-255, 659-694, 711, 893-900, 1043-1053):
     - `self.eval_core_rules` defaults to `False` in baseline (line 711), causing `_eval_guard_issue` to be skipped on baseline turns.
     - Multi-turn execution (`max_turns=3`) repeats prompts when sandbox errors occur.
     - Prefix caching enabled (`enable_prefix_caching=True`), but invalidated across heterogeneous multi-turn observation loops.
4. **Current Test Status**:
   - Command: `python -m pytest tests/test_eval_and_normalizer.py tests/test_time_resolver.py tests/test_profiler.py tests/test_sandbox_protocol.py -q`
   - Result: 41 passed in ~9.0 seconds.

---

## 2. LOGIC CHAIN

1. **Latency & Timeout Failure (Observation 2 + Observation 3)**:
   - Total time available: 21,600 seconds for 500 questions $\rightarrow$ $\le 43.2$ seconds/question gross, $\le 35$ seconds/question net.
   - A multi-turn observation loop requires 2-3 LLM generations (20-30s) + 2-3 code executions on large Excel/CSV datasets up to 300,000 rows (6-16s) $\rightarrow$ 37-55s per question.
   - If 50% of questions enter multi-turn loops, total inference time will exceed 6 hours, triggering Docker termination where uncompleted questions score 0, and losing the tie-breaker criteria.
2. **The Penalized Accuracy (PA) Penalty Trap (Observation 1 + Observation 2)**:
   - Under $E[\text{PA}] = 2p - 1$, answering is only mathematically rational when confidence $p > 0.5$.
   - Observation 1 shows 12/19 wrong questions finished on Turn 1 without detecting errors, and when errors or empty data occurred, the model hallucinated constants (`Tồn lớn nhất = 999.999.999 / 6`), hardcoded dates (`01/05`), or false `unanswerable`.
   - Allowing unconstrained LLM retries on suspicious results drives $p \ll 0.5$, converting potential 0.0 scores into -1.0 penalties. An explicit, deterministic Abstain Gate is mathematically mandatory.
3. **Data Messiness Invalidation of Naive Profiling (Observation 1)**:
   - In `biz_121` and `biz_122`, 47% of rows are blank in key fields due to merged Excel cells. Naive schema extraction in Step 1 passes these tables as normal, causing standard pandas filtering to drop half of line items.
   - Profiling cannot simply be schema inspection; it must be preceded by deterministic unmerging/forward-filling and categorical value indexing.
4. **Premature Fine-Tuning Conclusion (Observation 1)**:
   - All 19 failures in the dev set stem from missing cell unmerging, status label mismatch, date parsing flaws, and join suffix collisions. None are fundamentally unsolvable by prompt grounding and deterministic preprocessing. Fine-tuning before fixing these data pipelines is counterproductive.

---

## 3. CAVEATS

- **Hardware Testing Environment**: The critique is based on theoretical hardware bounds of the 2x RTX 5090 reference server (Blackwell architecture, 64GB VRAM total) and the empirical Colab A100 40GB run documented in `failure_analysis.md`. Actual physical execution on Blackwell GPUs may exhibit different vLLM kernel latency, though token generation bounds remain within the estimated ranges.
- **Private Test Distribution**: The private test set will contain new business types unseen in training. While our analysis addresses generalization via deterministic preprocessing, edge-case Excel formats unique to private test data could still present unanticipated structural anomalies.

---

## 4. CONCLUSION

- **Architectural Verdict**: The proposed 3-step pipeline is **FLAWED as an in-flight LLM multi-turn loop**, but **HIGHLY VALUABLE if converted into a deterministic pre-processing and single-turn inference architecture**.
- **What to Keep**: Compact schema representation, categorical value profiling (status enums), and suspicious result anomaly detection.
- **What to Adjust**:
  1. Replace runtime LLM exploration (Step 2) with a **Deterministic Pre-Profiler (Step 0)** executed in Python (< 0.2s) before prompt generation.
  2. Transform Step 3 into a **Hard Deterministic Abstain Gate**: If results are anomalous (0 rows, empty, NaN) and no deterministic recovery is available, immediately abstain (0.0 points) to protect PA.
  3. Enforce **Single-Turn Code Generation** to preserve prefix caching, minimize latency, and prevent Docker timeout.
- **Prioritized Roadmap**:
  - Priority 1: Robust Data Ingestion & Auto-Unmerger (Excel forward-fill).
  - Priority 2: Categorical Value Profiler (status values in prompt).
  - Priority 3: Time Resolver & Calendar Engine (Lunar/Solar Tết window, relative date bounds).
  - Priority 4: Hard Deterministic Abstain Gate.
  - Priority 5: Prompt Optimization & Safe Join / Line-item Aggregation Templates.
  - Priority 6: Model Retraining / SFT (LAST RESORT, after Priorities 1-5 achieve PA > +0.50).

---

## 5. VERIFICATION METHOD

To independently verify the claims, observations, and recommendations in this report:

1. **Verify Failure Analysis Observations**:
   ```powershell
   Get-Content "result/qwen25_14b_1m_code_only_rulebook_20261111_155610/eval_dev_30_colab_a100_40gb_ctx16384/failure_analysis.md" | Select-String "hoàn thành", "2.654", "38.878", "PA −0.5000", "12/19"
   ```
2. **Verify Competition Rules & Hardware Time Limits**:
   ```powershell
   Get-Content "docs/rule.md" | Select-String "5090", "6 giờ", "15B", "0.03"
   Get-Content "docs/evaluation.md" | Select-String "Penalized Accuracy", "total inference time"
   ```
3. **Verify Existing Unit Tests**:
   ```powershell
   python -m pytest tests/test_eval_and_normalizer.py tests/test_time_resolver.py tests/test_profiler.py tests/test_sandbox_protocol.py -q
   ```
4. **Invalidation Conditions**:
   - The critique of the multi-turn latency risk would be invalidated if private test set questions are reduced to $< 100$ or time limit extended beyond 12 hours.
   - The Abstain Gate mathematical proof ($p > 0.5$) would be invalidated only if the scoring metric drops the $-1.0$ penalty for wrong answers.
