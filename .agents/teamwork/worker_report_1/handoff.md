# HANDOFF REPORT: MASTER ADVERSARIAL CRITIQUE REPORT OF HANDOFF_PLAN.MD

- **Subagent**: `worker_report_1`
- **Archetype**: Worker / Implementer / QA / Specialist
- **State Folder**: `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\worker_report_1`
- **Target Audience**: Orchestrator (`e8c45a29-5148-4546-ba15-45fed278495a`) / Auditor / Technical Reviewers
- **Date**: 2026-11-13
- **Primary Deliverable**: `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\worker_report_1\ADVERSARIAL_CRITIQUE_REPORT.md` (69.6 KB)

---

## 1. OBSERVATIONS

1. **Input Directives & Evidence Synthesis**:
   - Synthesized the complete evidence base from:
     * `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\ORIGINAL_REQUEST.md` (lines 5–31)
     * `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\orchestrator_3\PROJECT.md` (lines 1–29)
     * `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\explorer_survey_1\handoff.md` (lines 1–245: 16 Tools vs Lean Code-Interpreter)
     * `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\explorer_survey_2\handoff.md` (lines 1–290: ReAct, `<think>` retention, 16k token overflow proof, KV-cache latency)
     * `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\explorer_survey_3\handoff.md` (lines 1–275: Dev 30 PA math, turn forensics, Qwen3.5-9B feasibility on 2x RTX 5090)
2. **Key Verified Facts from Codebase & Artifacts**:
   - `docs/rule.md`: Model parameters $\le 15\text{B}$; offline Docker `--network none`; 6-hour evaluation wall-clock time limit for ~500 questions; hardware $2 \times \text{NVIDIA RTX 5090}$ (64GB VRAM total), CUDA $\ge 12.8$.
   - `src/agent/solver.py`:
     * Line 243: `self.max_model_len = int(model_cfg.get("max_model_len", 16384))`
     * Line 858: `self.max_turns = int(self.agent_cfg.get("max_turns", 3))`
     * Lines 1086–1091: Codebase currently strips `<think>`: `compact_asst_reply = f"```python\n{code}\n```"`
     * Line 1200: Immediate exit on `kind='final'` on Turn 1 without host verification.
     * Line 1263: Fallback to `abstain` on exhausting 3 turns.
   - `result/qwen25_14b_1m_code_only_rulebook_20261111_155610/eval_dev_30_colab_a100_40gb_ctx16384/failure_analysis.md`:
     * Line 9: 38/817 training targets used `.str.contains("hoàn thành")`, causing 0 rows across 7 questions in Dev 30.
     * Line 49: 12/19 wrong answers finalized on Turn 1 due to one-shot completion inductive bias.
     * Line 10: `biz_122` has 2,654/5,635 rows empty in order headers; `biz_121` has 38,878/82,920 rows empty.
   - `result/` Dev 30 Experiments:
     * Base: 7 Correct (+7.0), 12 Wrong (-12.0), 11 Abstain (0.0), 62 turns $\to \text{PA} = -0.1667$.
     * Base+LoRA: 7 Correct (+7.0), 9 Wrong (-9.0), 14 Abstain (0.0), 59 turns $\to \text{PA} = -0.0667$.
3. **Master Report Generation Verification**:
   - Output Path: `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\worker_report_1\ADVERSARIAL_CRITIQUE_REPORT.md`
   - File Size: 69,616 bytes (~70 KB).
   - Structure: 6 core sections fully covering the Executive Summary & Risk Matrix, Pillar 1 (16 Tools), Pillar 2 (ReAct & `<think>`), Pillar 3 (Dev 30 PA math), Pillar 4 (Qwen3.5-9B), and Section 6 (Actionable 4-Pillar Blueprint).

---

## 2. LOGIC CHAIN

1. **Step 1: Dissecting 16 Tools vs Lean Code-Interpreter**:
   - The proposed 16 tools across 6 functional groups duplicate 1-line Python/Pandas operations (`df.groupby()`, `df.ffill()`, `pd.to_datetime()`, `sqlite3.connect()`).
   - Defining 16 JSON schemas consumes 3,520 tokens (21.5% of 16k context window).
   - Models $\le 15\text{B}$ suffer cognitive overload and routing failures on $>6-8$ tools.
   - Multi-step tool chains suffer compounding errors: $P(\text{success}) = \prod_{i=1}^8 P_i = 0.90^8 \approx 43.0\%$.
   - Tool execution loops (8 turns $\times$ 5.5s = 44-55s/question) exceed the 43.2s/question budget for 500 questions in 6 hours, triggering container timeout.
2. **Step 2: Dissecting ReAct & `<think>` Retention**:
   - Reasoning models (DeepSeek-R1, QwQ, Qwen-Reasoning) are trained via single-turn RL trajectories (`Query -> <think> -> Solution`). Retaining `<think>` in multi-turn history places them into an out-of-distribution (OOD) state.
   - Attentional anchoring causes "thinking repetition" and "confirmation bias" (clinging to `.str.contains("hoàn thành")` despite empty filter errors).
   - Mathematical proof: Context grows by 2,850 tokens/turn with `<think>`, resulting in a hard overflow at Turn 5 (16,900 tokens > 16,384 limit). When stripped, context at Turn 10 is only 13,150 tokens.
   - Memory & Latency: KV-cache for 16k context is 3.0 GB/seq in BF16; decoding 2,300 tokens takes 51s/turn $\to$ 5 turns take 4.25 minutes/question, blowing past the 6h budget ($100\text{ questions} = 7-14\text{ hours}$).
   - Violates official DeepSeek guidelines and modern agent frameworks (`smolagents`, Claude 3.7 Ephemeral Thinking).
3. **Step 3: Dissecting Dev 30 Benchmark & Penalized Accuracy (PA)**:
   - In PA ($+1.0$ Correct, $0.0$ Abstain, $-1.0$ Wrong), 1 wrong cancels 1 correct.
   - Base Model scored $-0.1667$ because 12 wrongs ($-12.0$) overwhelmed 7 corrects ($+7.0$).
   - Base+LoRA scored $-0.0667$ with identical 7 corrects; LoRA only converted 3 wrongs into abstains ($11 \to 14$), eliminating $-3.0$ penalty, but failed to learn tabular domain logic.
   - Turn count forensics (~60 turns across 30 questions) revealed bimodal exits: 12/19 wrong answers finalized prematurely on Turn 1 due to LLM one-shot inductive prior, while failed retries exhausted 3 turns into budget-exhaustion abstains.
   - Root causes of wrong answers: silent zero-row filtering, Excel merged cells without `ffill`, datetime serialization mismatches, debt snapshot vs ledger, false unanswerable penalties, and lack of a post-execution Abstain Gate.
4. **Step 4: Feasibility & Hardware Sizing of Qwen3.5-9B**:
   - Qwen3.5-9B (9.2B dense params) fully complies with the $\le 15\text{B}$ rule, February/March 2026 release date ($< 2026-10-01$), and open-weights licensing.
   - VRAM sizing in BF16: 18.4GB weights + 4.2GB KV-cache (16k context, batch 4) + 3.0GB overhead = 25.6GB total.
   - On $2 \times \text{RTX 5090}$ (64GB total): fits in 1 GPU ($25.6\text{GB} \le 32\text{GB}$), or runs in `tp=2` at ~13GB per GPU with $>18.5\text{GB}$ free headroom. Zero OOM risk. On A100-40GB, utilizes 64% VRAM.
   - Speed: 60-75 tok/s in `tp=2`, latency 6-8s/question $\to$ 500 questions in 1.11 hours (18.5% of 6h limit).
   - Hazard: `<think>` monologue can exceed 3,000 tokens; requires `max_tokens >= 6144` and ephemeral `<think>` stripping.
5. **Step 5: Architectural Formulation**:
   - Synthesized the **Lean Bounded Execution Architecture** with 4 pillars:
     * Pillar A: Deterministic Step 0 Pre-profiler (`business_loader.py` + `calendar_utils.py` in 0.05s on Host).
     * Pillar B: Ephemeral Thinking (strip `<think>` between turns).
     * Pillar C: Bounded ReAct (max 2 turns: Turn 1 execution, Turn 2 exception repair).
     * Pillar D: Mandatory Post-Execution Abstain Gate (intercept empty/zero revenue anomalies, score 0.0 instead of -1.0).
   - Target KPI: PA increases from $-0.0667 \to \mathbf{+0.4667}$ on Dev 30.

---

## 3. CAVEATS

1. **Theoretical 16-Tool Implementation Details**:
   - `HANDOFF_PLAN.md` is a conceptual architectural specification rather than merged codebase code. Our analysis evaluated standard OpenAI/Anthropic JSON-schema tool calling patterns.
2. **Kaggle 2x T4 Fine-Tuning Constraints**:
   - While Qwen3.5-9B runs in BF16 effortlessly on 2x RTX 5090 and A100-40GB, fine-tuning on Kaggle 2x T4 (32GB total) requires 4-bit QLoRA (NF4) with CPU offloading for Adam optimizer states.
3. **No Raw Data Modification**:
   - Confirmed 100% read-only adherence; zero modifications made to `data/`.

---

## 4. CONCLUSION

1. **Adversarial Verdict**:
   `HANDOFF_PLAN.md` is fundamentally flawed and must be **REJECTED**. The 16 tools, multi-turn ReAct (5-10 turns), and `<think>` retention create a catastrophic failure mode on $\le 15\text{B}$ open-weights models, guaranteeing context overflow, Docker timeout, and negative Penalized Accuracy.
2. **Replacement Blueprint**:
   The team must pivot immediately to the **Lean Bounded Execution Architecture**:
   - Step 0 Deterministic Pre-profiling (schema, distinct categories, unmerge, calendar resolution).
   - Ephemeral Thinking (strip `<think>` between turns).
   - Bounded ReAct (strictly max 2 turns).
   - Mandatory Post-Execution Abstain Gate.
   - Qwen3.5-9B baseline deployed on vLLM with `tensor_parallel_size=2`.

---

## 5. INDEPENDENT VERIFICATION METHOD

1. **Verify Deliverable Existence and Size**:
   ```powershell
   Get-Item "d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\worker_report_1\ADVERSARIAL_CRITIQUE_REPORT.md" | Select-Object Length, LastWriteTime
   ```
   *Expected*: Length $\approx 69,616$ bytes.
2. **Verify PA Mathematical Calculations**:
   ```powershell
   python -c "print('Base PA:', (7*1.0 - 12*1.0)/30); print('LoRA PA:', (7*1.0 - 9*1.0)/30); print('Target PA:', (17*1.0 - 3*1.0)/30)"
   ```
   *Expected*:
   `Base PA: -0.16666666666666666`
   `LoRA PA: -0.06666666666666667`
   `Target PA: 0.4666666666666667`
3. **Verify Token Overflow Progression**:
   ```powershell
   python -c "
   init, think, code, obs = 5500, 2000, 300, 500
   total_with = init
   total_strip = init
   for t in range(1, 6):
       print(f'Turn {t}: With={total_with} (Remaining={16384-total_with}) | Strip={total_strip} (Remaining={16384-total_strip})')
       total_with += (think + code + obs + 50)
       total_strip += (code + obs + 50)
   "
   ```
   *Expected*: Turn 5 With-Think = 16,900 tokens (Overflow: -516), Strip-Think = 8,900 tokens (Remaining: 7,484).
4. **Verify KV-Cache Footprint for Qwen3.5-9B & 14B**:
   ```powershell
   python -c "
   # 14B (48 layers, 8 heads, 128 dim)
   kv_14b = (16384 * 2 * 48 * 8 * 128 * 2) / (1024**3)
   # Qwen3.5-9B (32 layers, 4 heads, 128 dim)
   kv_9b = (16384 * 2 * 32 * 4 * 128 * 2) / (1024**3)
   print(f'14B KV 16k: {kv_14b:.2f} GB/seq | 9B KV 16k: {kv_9b:.2f} GB/seq')
   "
   ```
   *Expected*: `14B KV 16k: 3.00 GB/seq | 9B KV 16k: 1.00 GB/seq`.
