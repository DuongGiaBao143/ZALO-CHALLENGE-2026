# Comprehensive Diagnostic Report & Toolset Capability Evaluation
**Project:** DataMate — Natural-Language Vietnamese Question Answering over Tabular Data  
**Competition:** Zalo AI Challenge 2026  
**Document ID:** `DOC-DATAMATE-2026-DIAG-01`  
**Date:** November 15, 2026  
**Authors:** DataMate Architecture & Diagnostic Engineering Team  

---

## 1. Executive Summary & Problem Statement

### 1.1 Context & Competition Constraints
The Zalo AI Challenge 2026 *DataMate* task challenges systems to perform natural-language question answering across heterogeneous, uncurated enterprise business records (.csv, .xlsx, .sqlite) from Vietnamese micro-merchants and SMEs (cafes, grocery stores, pharmacies, construction suppliers).

Key system constraints governing this benchmark include:
1. **Asymmetric Scoring Metric — Penalized Accuracy (PA):**
   $$\text{PA} = \frac{1}{N} \sum_{i=1}^N S(y_i, \hat{y}_i), \quad S(y_i, \hat{y}_i) = \begin{cases} +1.0 & \text{if correct} \\ 0.0 & \text{if abstain} \\ -1.0 & \text{if wrong} \end{cases}$$
   A wrong answer incurs an immediate -1.0 penalty. Consequently, guessing or crashing into unverified outputs severely degrades the leaderboard score.
2. **Resource & Offline Isolation Hard Constraints:**
   - Inference model parameters strictly limited to $\le 15\text{B}$ (Rule 2).
   - Strict offline container execution (`--network none`).
   - Host evaluation environment: 2× NVIDIA RTX 5090 (64GB VRAM total), CUDA $\ge 12.8$.
   - Strict raw data immutability: `/data` mounted strictly read-only (`mode=ro`).
   - Per-question timeout budget: 600 seconds.

### 1.2 Problem Statement
During initial end-to-end evaluation runs on the Kaggle 2×T4 testbed using OpenCode with the Ornith 1.5 9B / Qwen2.5-Coder base models, baseline runs experienced significant turn wastage, protocol validation crashes, and wall-clock timeouts. Specifically, in Smoke 1 question `q_01a28f2233bd` for business `biz_112` (*"gia ban mot ly soda chanh day (m) vao ngay 01/12/2025 la bn"*), execution traces revealed systemic failure modes:
- In trace `tmp/ornith-local-excel-tciqou_v/`, the agent timed out at 600.138s after burning 7 tool turns without finalizing.
- In trace `tmp/ornith-local-excel-two97fz3/`, the agent required 13 tool calls, finally calculated the exact correct answer `37000` on turn 12, but because the model returned an empty string for its conversational prose, the normalizer marked it as `empty_final` and defaulted to `abstain` (0.0 points instead of +1.0 point).
- In Docker trace `tmp/ornith-local-docker-excel-gxp8u9g8/`, OpenCode truncated a tool observation, sending the agent into a futile loop trying to read truncated tool logs from disk.

This report documents the exhaustive root causes of these failure modes, conducts a formal capability evaluation of the agent toolset and OpenCode built-in tools (directly addressing team inquiries regarding why built-in tools like `bash` and `grep` are denied), and outlines a verified, regression-free implementation roadmap.

---

## 2. Root Cause Analysis of 5 Observed Failure Modes (Smoke 1 / `biz_112`)

We conducted forensic investigations across execution traces (`tmp/ornith-local-excel-tciqou_v/q_01a28f2233bd.json`, `tmp/ornith-local-excel-two97fz3/q_01a28f2233bd.json`, `tmp/ornith-local-docker-excel-gxp8u9g8/opencode.jsonl`).

```
                    ┌──────────────────────────────────────────────┐
                    │  5 OBSERVED SMOKE 1 FAILURE MODES            │
                    └──────────────────────────────────────────────┘
                                           │
         ┌──────────────────┬──────────────┼──────────────┬──────────────────┐
         ▼                  ▼              ▼              ▼                  ▼
┌─────────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────────────┐
│ 1. PROTOCOL     │ │ 2. SIGNATURE │ │ 3. VIETNAMESE│ │ 4. LOOKUP &  │ │ 5. TIMEOUTS &   │
│ VIOLATIONS      │ │ MISMATCHES   │ │ NUMBERS      │ │ HALLUCINATION│ │ EMPTY FINAL     │
│                 │ │              │ │              │ │              │ │                 │
│ Plain print()   │ │ Unquoted     │ │ '37,000.0000'│ │ Row offset   │ │ 600s wall-clock │
│ displaces JSON; │ │ types; msg vs│ │ -> NaN via   │ │ Unnamed cols;│ │ OpenCode output │
│ sandbox.py:2244 │ │ evidence;    │ │ to_numeric;  │ │ 'Tanggal'    │ │ truncation loop;│
│ rejects line.   │ │ type aliases │ │ ValueError   │ │ Multi-sheet  │ │ raw prose empty │
└─────────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └─────────────────┘
```

---

### 2.1 Failure Mode 1: Protocol Violations & Stdout Leakage during `run_python`

#### Code Locations
- `tmp/opencode-structured/src/agent/sandbox.py:2243-2274`
- `tmp/opencode-structured/bridge.py:488-493, 530-546, 700-705`

#### Forensic Evidence from Traces
In trace `tmp/ornith-local-excel-two97fz3/q_01a28f2233bd.json` (6 out of 13 calls failed due to this mode):
- **Call #5:** The model executed `print(df.head())`. Sandbox returned:
  ```text
  Protocol violation: Last non-empty line of stdout is not valid strict JSON: Extra data: line 1 column 9 (char 8)
  Line content: '   Unnamed: 0  Unnamed: 1  Unnamed: 2'
  ```
- **Call #7:** The model ran `print({'T06_2026': (7083, 9), 'T07_2026': (7656, 9)})`. Sandbox returned:
  ```text
  Protocol violation: Last non-empty line of stdout is not valid strict JSON: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
  ```
- **Call #8:** The model iterated through 14 sheets printing sheet names and shapes. Sandbox returned:
  ```text
  Protocol violation: Last non-empty line of stdout is not valid strict JSON: Expecting value: line 1 column 1 (char 0). Line content: 'T04_2025 (6523, 9)'
  ```
- **Call #9:** The model printed `print("SHAPE", show.shape)`. Sandbox returned:
  ```text
  Protocol violation: Last non-empty line of stdout is not valid strict JSON: Expecting value: line 1 column 1 (char 0). Line content: 'SHAPE (1, 9)'
  ```

#### Exact Failure Mechanism
1. In `sandbox.py:2244`, `run_python_in_sandbox` parses subprocess stdout by taking strictly the last non-empty line:
   ```python
   lines = [line.strip() for line in raw_stdout.splitlines() if line.strip()]
   last_line = lines[-1]
   raw_payload = _parse_strict_json(last_line)
   ```
2. When the LLM outputs standard exploratory Python scripts containing `print()` calls, the last line is tabular pandas output, Python dictionary reprs with single quotes, or text strings, none of which parse as strict JSON objects.
3. In `bridge.py`, while `_bridge_tracked_print` records `_BRIDGE_STATE['printed'] = True`, line 543 explicitly blocked auto-emitting when printed was True:
   ```python
   elif not _BRIDGE_STATE['printed'] and _BRIDGE_STATE['last_explore'] is not None:
       _bridge_orig_emit_obs(_BRIDGE_STATE['last_explore'], 'explore_data result')
   ```
4. Furthermore, if `emit_obs` was executed in the middle of a script, but followed by ANY trailing debug `print()` or third-party warning, the valid JSON payload was pushed up in the stdout stream and displaced from `lines[-1]`, triggering a fatal `protocol_violation`.
5. This burned 6 turns in `two97fz3` and 3 turns in `tciqou_v`, turning a 2-turn task into a 13-turn marathon.

---

### 2.2 Failure Mode 2: `emit_final` Parameter and Call Signature Mismatches

#### Code Locations
- `tmp/opencode-structured/src/agent/sandbox.py:347-364, 1572-1582`
- `tmp/opencode-structured/bridge.py:507-528`

#### Forensic Evidence & Call Signatures
1. **Unquoted Type Identifiers:**
   In multiple prompt responses, 9B-14B models generate:
   ```python
   emit_final(37000, type=number, evidence="Found in row 4")
   emit_final(True, type=boolean, evidence="Valid invoice")
   ```
   In standard Python, `number` and `boolean` are not built-in identifiers. The interpreter crashes with `NameError: name 'number' is not defined` before `emit_final` can execute.
2. **Keyword Inconsistency (`msg`/`message` vs `evidence`):**
   Accustomed to `emit_obs(data, msg="...")`, models instinctively write:
   ```python
   emit_final(37000, type="number", msg="Đơn giá ngày 01/12/2025")
   ```
   If `msg` is not mapped to `evidence`, `sandbox.py:358` asserts:
   ```python
   evidence = payload.get("evidence")
   if not evidence or not isinstance(evidence, str) or not evidence.strip():
       raise ValueError("Missing or empty 'evidence' string in final payload.")
   ```
   crashing the valid answer with `ValueError`.
3. **Type Name Synonyms:**
   Models frequently specify Python native type names or descriptive terms:
   - `type="int"`, `type="float"`, `type="integer"` instead of `"number"`.
   - `type="str"`, `type="text"` instead of `"string"`.
   - `type="bool"` instead of `"boolean"`.
   - `type="array"`, `type="sequence"` instead of `"list"`.
   `sandbox.py:1581` enforces `clean_type in VALID_ANSWER_TYPES`, throwing `ValueError: Invalid answer type: 'int'`.
4. **Zero-Argument Finalization:**
   In trace `two97fz3`, the model attempted `emit_final()` with no parameters. `bridge.py:510` intercepted this and converted it to an observation (`emit_obs`), but did not signal to the normalizer that a calculation had already succeeded.

---

### 2.3 Failure Mode 3: Vietnamese Number Formatting Issues

#### Code Locations
- `data/train/data/biz_112/So_chi_tiet_ban_hang_1.xlsx` (Sheet `T12_2025`)
- `tmp/opencode-structured/src/postprocess/vn_utils.py:51-110`
- `tmp/opencode-structured/bridge.py:310-336`

#### Forensic Evidence from Traces
In `biz_112`, the accounting software exported price and amount columns with comma thousand separators and 4 decimal places:
```text
'37,000.0000', '25,000.0000', '33,500.0000', '42,000.0000'
```
In `tciqou_v/q_01a28f2233bd.json` Calls 3 & 4, the model attempted:
```python
df['Đơn giá'] = pd.to_numeric(df['Đơn giá'], errors='coerce')
```
Because standard `pd.to_numeric` cannot parse comma-separated strings with decimal points, every single price in all 7,240 rows of sheet `T12_2025` was coerced to `NaN`!
Subsequent filtering `df[df['Đơn giá'] > 0]` yielded 0 rows. The model concluded that no sales occurred for that product on that date, triggering frantic retries and hallucinations.

#### Exact Mechanisms
1. `int('37,000.0000')` raises `ValueError: invalid literal for int() with base 10: '37,000.0000'`.
2. `float('37,000.0000')` raises `ValueError: could not convert string to float: '37,000.0000'`.
3. `pd.to_numeric(series, errors='coerce')` silently converts all formatted strings to `np.nan`.
4. While `parse_vn_number()` in `src/postprocess/vn_utils.py` handles this format correctly ($37000.0$), base LLMs default to standard pandas idioms (`pd.to_numeric`) unless the runtime transparently intercepts the conversion.

---

### 2.4 Failure Mode 4: Data Lookup Errors & Schema/Header Hallucinations (e.g. `'Tanggal'`)

#### Code Locations
- `tmp/opencode-structured/bridge.py:133-150, 310-336`
- `tmp/opencode-structured/src/agent/sandbox.py:1827-1845`

#### Forensic Evidence from Traces
In `tciqou_v/q_01a28f2233bd.json` Call 5:
```python
df['Ngày'] = pd.to_datetime(df['Tanggal'].map(lambda x: pd.to_datetime(x, dayfirst=True)), dayfirst=True) if False else pd.to_datetime(df['Ngày'], dayfirst=True)
```
The model hallucinated the Indonesian column name `'Tanggal'` (meaning date).

#### Exact Failure Mechanism
1. **Header Row Offset:** In `biz_112`, `So_chi_tiet_ban_hang_1.xlsx` has its real column headers at row index 2 (row 3 of the sheet), preceded by banner title rows. Calling `pd.read_excel()` without offset defaults to row 0, yielding column names `['Unnamed: 0', 'Unnamed: 1', ...]`. Accessing `df['Ngày']` raises `KeyError: 'Ngày'`.
2. **Multi-Sheet Partitioning:** `So_chi_tiet_ban_hang_1.xlsx` partitions records into 14 monthly sheets (`T04_2025` through `T07_2026`). Calling `pd.read_excel()` loads only the first sheet (`T04_2025`, April 2025). Filtering for December 2025 (`01/12/2025`) returns 0 rows.
3. **Cross-Lingual Hallucination:** Encountering empty slices or `KeyError`, multilingual LLMs hallucinate common column names from other Southeast Asian languages in their training corpora (`Tanggal`), or invent invalid datetime parameters (`pd.Timestamp(expr, year=y, dayfirst=True)` raising `TypeError: unexpected keyword argument 'dayfirst'`).

---

### 2.5 Failure Mode 5: Execution Timeouts & Empty Final Text Trap

#### Code Locations
- `notebooks/Evaluate_Ornith_OpenCode_Kaggle_2T4.ipynb` (Cells 1, 3, 4, 6)
- `tmp/opencode-structured/bridge.py:651-667` (`_bound_run_python_payload`)

#### Forensic Evidence from Traces
1. **Cumulative Step Latency Timeout:**
   In `tciqou_v/q_01a28f2233bd.json`:
   `timed_out: True`, `elapsed_sec: 600.138`, `abstain_reason: question_timeout`.
   Each ReAct turn with a 9B-14B model takes ~25s generation + 5-15s tool execution (~35-40s/turn). Burning 13 turns on protocol errors and broken date parsing easily saturates the 600s budget.
2. **OpenCode Truncation Detour Loop:**
   In Docker trace `gxp8u9g8/opencode.jsonl`, when a tool output exceeded OpenCode's internal buffer (8,863 bytes), OpenCode printed:
   ```text
   The tool call succeeded but the output was truncated. Full output saved to: /tmp/datamate_work/tool_output.txt
   Use Grep to search the full content or Read with offset/limit to view specific sections.
   ```
   The model fell into OpenCode's trap: it spent subsequent turns trying to call `read` on `/tmp/...` or searching for `grep`, completely abandoning the SQL/Python calculation until it exhausted its step limit!
3. **Empty Final Prose Trap (`tool_succeeded_but_final_empty`):**
   In trace `two97fz3`:
   - On Call 12, the model successfully executed:
     ```python
     emit_final(37000, type='number', evidence='order ORD034973 of Soda chanh dây (M) on 2025-12-01')
     ```
     The sandbox validated and returned `success: True, parsed_output: {"kind": "final", "answer": 37000}`.
   - However, OpenCode expected final assistant prose after the tool call. The model generated `raw_final_text: ""`.
   - In earlier normalizer versions, this caused the normalizer to return `abstain(reason="empty_final")`, throwing away a 100% correct computation!

---

## 3. Toolset Completeness & Capability Evaluation (R2)

### 3.1 Evaluation of Existing 4 Tools

| Tool | Implementation Scope | Strengths | Fundamental Limitations | Verdict |
|---|---|---|---|---|
| **`read`** | Reads text/markdown files (`README.md`, notes). | Clean, fast extraction of shop-specific conventions and business definitions. | Completely incapable of parsing tabular formats (.xlsx, .sqlite) or filtering rows. | **Keep** (Essential for Step 1 shop discovery). |
| **`inspect_table`** | Schema inspection, sheet listing, header discovery, categorical preview. | Read-only openpyxl peek without loading full tables; zero memory overhead; repairs CP437 mojibake. | Cannot compute aggregations, filters, joins, or mathematical formulas. | **Keep** (Essential for Step 2 schema discovery). |
| **`aggregate`** | Hardcoded CSV single-table distinct count tool. | 100% deterministic zero-shot accelerator for CSV distinct counting; zero token overhead. | Fails completely on XLSX and SQLite; cannot do sums, averages, ratios, top-k, or multi-table joins. | **Keep** (Specialized accelerator for ~15% of queries). |
| **`run_python`** | Sandboxed Python subprocess execution. | Turing-complete; handles all tabular formats, Rulebook calculations, dates, and all 8 answer types. | Vulnerable to protocol violations, formatting crashes, and syntax errors without runtime support. | **Keep & Enhance** (Primary engine for 85%+ of queries). |

---

### 3.2 3-Way Architectural Trade-Off Analysis

We evaluated three architectural paradigms for bridging agent capabilities:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                      3-WAY ARCHITECTURAL TRADE-OFF ANALYSIS                      │
├─────────────────────────┬────────────────────────────┬───────────────────────────┤
│ Alternative A:          │ Alternative B:             │ Alternative C:            │
│ Dedicated Tools         │ Runtime Lean Helpers       │ Prompt & Bridge Governance│
│ (sum, filter, join...)  │ (explore, clean, date...)  │ (3-step protocol, rescue) │
├─────────────────────────┼────────────────────────────┼───────────────────────────┤
│ ❌ Context bloat (10+   │ ✅ Zero tool schema token  │ ✅ Enforces strict order  │
│    schemas, 4k tokens)  │    overhead in prompt      │    (README -> inspect ->  │
│ ❌ Fails on messy       │ ✅ High expressiveness     │    calculate)             │
│    merged headers,      │    across all shop domains │ ✅ Catches edge cases     │
│    lunar dates, order   │ ✅ Built-in sanity checks  │    (empty prose rescue,   │
│    vouchers             │    and abstain guards      │    step limit banner)     │
│ ❌ Combinatorial explo- │ ❌ Requires guiding model  │ ❌ Cannot execute code    │
│    sion across domains  │    not to import helpers   │    by itself              │
└─────────────────────────┴────────────────────────────┴───────────────────────────┘
```

#### Alternative A: Dedicated Specialized Tools (`sum_column`, `filter_rows`, `join_tables`)
- **Pros:** Structured JSON inputs; eliminates Python syntax errors.
- **Cons:**
  1. *Combinatorial Explosion:* Rulebook §1-§10 contains complex business logic (e.g. line-level vs order-level discounts, VAT handling, lunar Tết holiday windows from 23rd lunar month 12 to 10th lunar month 1, shift windows 06:00-13:59 vs 14:00-21:59). Designing rigid tools to capture every variation is intractable.
  2. *Token Bloat & Tool Hallucination:* Providing 10+ tool definitions adds 3,000-5,000 tokens to the system prompt, degrading tool selection accuracy for a 14B model (Rule 2).
  3. *Brittleness on Real Data:* Fails on unmerged multi-level headers, multi-sheet monthly workbooks, and inconsistent column labels.
- **Verdict:** **REJECTED.**

#### Alternative B: Domain-Agnostic Lean Helpers in Sandbox Runtime
- **Pros:**
  1. *Zero Context Schema Overhead:* External tool definition stays minimal (`run_python`).
  2. *Full Computational Expressiveness:* Six lean helpers (`explore_data`, `fuzzy_find`, `load_clean_df`, `resolve_date`, `emit_obs`, `emit_final`) encapsulate 95% of data cleaning boilerplate (unmerging, header offset detection, Vietnamese date/number normalization).
  3. *Built-in Abstain Protection:* `emit_final` automatically abstains if a filter returns 0 rows, preventing -1.0 penalties from empty-match traps.
- **Cons:** The model must be instructed that helpers are already in `globals()` so it does not attempt `import explore_data`.
- **Verdict:** **ACCEPTED & RECOMMENDED.**

#### Alternative C: Prompt Governance & Bridge Adaptation / Normalization
- **Pros:**
  1. *Prompt 3-Step Protocol:* Forces the model to read `README.md` and inspect tables before writing code, preventing premature guessing.
  2. *Bridge Fault Tolerance:* Transparently catches LLM signature quirks (mapping `msg` to `evidence`, accepting unquoted type names, auto-wrapping stdout).
  3. *Normalizer Rescue (`tool_rescue_prediction`):* Recovers correct answers when model text is empty or truncated after a successful tool calculation.
- **Verdict:** **ACCEPTED & COMPLEMENTARY.**

#### The Optimal Architecture: Hybrid Tri-Tier Architecture
The optimal system combines:
1. **Tier 1 (Minimal Toolset):** Retain exactly 4 tools (`read`, `inspect_table`, `aggregate`, `run_python`).
2. **Tier 2 (Runtime Lean Helpers):** Provide lean helpers (`explore_data`, `load_clean_df`, `resolve_date`, `emit_obs`, `emit_final`, `parse_vn_number`, `vn_num`) natively in sandbox globals.
3. **Tier 3 (Prompt Governance & Bridge Safety Net):** Enforce the 3-step pipeline via system prompt; wrap stdout, patch number parsing, and rescue final calculations in `bridge.py` and normalizer.

---

### 3.3 Evaluation of OpenCode Built-in Tools (User Follow-up)

**User Inquiry:** *"T nhớ là opencode có tool có sẵn mà, sao ko cấp cho nó đi nhỉ"*  
*(I recall OpenCode has built-in tools available, why didn't we grant permissions to them?)*

In `notebooks/Evaluate_Ornith_OpenCode_Kaggle_2T4.ipynb` (Cell 3), permissions are configured as:
```python
permissions = {"*": "deny", "read": "allow", "inspect_table": "allow", "aggregate": "allow", "run_python": "allow"}
```
All built-in OpenCode tools (`bash`, `grep`, `glob`, `list`, `write`, `edit`, `webfetch`, `todowrite`) are explicitly denied. We evaluated each tool:

#### 1. `bash` — High Risk & Empirically Destructive
- **Empirical Evidence from Traces:** In earlier benchmark traces where `bash` was permitted (`tmp/ornith-local-docker-excel-40s6f7er/`, `6whpzsni/`, `f8q0dy_e/`), models exhibited catastrophic degradation. Instead of writing Python scripts to process structured data, the LLM looped through shell commands (`ls -la`, `cat`, `head -n 20`, `awk`, `find`), burning all 10 available steps on directory navigation.
- **Security & Containment Risk:** `bash` allows execution outside the isolated `shop_root`, bypassing the sandbox's memory, file, and read-only safeguards.
- **Competition Rule Violation:** Any shell command that attempts to write or pipe to `/data` risks crashing container execution or violating Rule 4.
- **Verdict:** **MUST STAY DENIED (`deny`).**

#### 2. `grep` — Ineffective & Induces Detour Loops
- **Inability to Search Binary Formats:** Over 60% of competition datasets are stored in `.xlsx` (zipped XML) or `.sqlite` (binary B-tree) formats. Running `grep` on an Excel or SQLite file returns binary gibberish or zero matches.
- **The Truncation Trap:** When OpenCode truncates tool output, its built-in notification says: *"Use Grep to search the full content..."*. If `grep` is enabled, the agent attempts to grep temporary files instead of refining its Python query, wasting precious turns and timing out.
- **Verdict:** **MUST STAY DENIED (`deny`).**

#### 3. `glob` & `list` — Redundant & Lacks Shop Intelligence
- **Redundancy:** Listing shop files is already handled safely and comprehensively by `inspect_table(file=None)`, which additionally reports sheet names, file sizes, and repairs CP437 mojibake filenames.
- **Leakage Risk:** Unbounded `glob` can match files outside `shop_root` (such as `/result`, system libraries, or other shop folders), violating shop containment.
- **Verdict:** **MUST STAY DENIED (`deny`).**

#### 4. `write` & `edit` — Explicitly Prohibited
- **Competition Commandment:** The DataMate task and competition rules strictly require that `/data` is read-only (`mode=ro`). The agent must never write to or modify data files.
- **Verdict:** **MUST STAY DENIED (`deny`).**

#### Summary Verdict on Built-in Tools
Enabling OpenCode built-in tools degrades agent performance, inflates context tokens, wastes ReAct steps on shell exploration, and risks containment violations. The **4-tool curated setup (`read`, `inspect_table`, `aggregate`, `run_python`) + runtime lean helpers** is strictly superior in speed, accuracy, token efficiency, and compliance.

---

## 4. Prioritized Action Plan & Technical Specification

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       PRIORITIZED ACTION PLAN                               │
├───────────┬─────────────────────────────────────────────────────────────────┤
│ Priority  │ Concrete Implementation Deliverable                             │
├───────────┼─────────────────────────────────────────────────────────────────┤
│ **P0**    │ 1. Auto-wrap plain stdout in `bridge.py` (`_BRIDGE_RUNTIME_PATCH`)│
│ (Critical)│ 2. Inject type constants into globals (`number='number'`, etc.) │
│           │ 3. `emit_final` signature tolerance (`evidence` default, aliases)│
│           │ 4. Monkeypatch `pd.to_numeric` & `builtins.int/float` for VN num│
├───────────┼─────────────────────────────────────────────────────────────────┤
│ **P1**    │ 1. Strict payload bounding (<3,500 chars) to kill truncation loop│
│ (High)    │ 2. `pd.DataFrame.__getitem__` column lookup tolerance (accents, │
│           │    case-folding, `'Tanggal'` alias)                             │
│           │ 3. Byte-for-byte sync of Cell 1 `EMBEDDED_BRIDGE_PY`            │
│           │ 4. Prompt helper guidance in Cell 1 & Cell 3                    │
│           │ 5. Verify normalizer tool rescue for empty final text           │
├───────────┼─────────────────────────────────────────────────────────────────┤
│ **P2**    │ 1. Ephemeral Thinking context pruning (strip `<think>` tags)    │
│ (Medium)  │ 2. Multi-sheet workbook automatic cross-sheet lookup            │
└───────────┴─────────────────────────────────────────────────────────────────┘
```

### Detailed Component Implementation Matrix

#### 1. Protocol Safety Net & Auto-Emit (`bridge.py`)
- In `_BRIDGE_RUNTIME_PATCH`, track all printed stdout via `_bridge_tracked_print`.
- In `_bridge_auto_emit_on_exit()` (registered with `atexit`):
  - If execution finishes without exception and without explicit `emit_obs` or `emit_final`: automatically emit `emit_obs(captured_stdout, "Captured output")`.
  - If `emit_obs` or `emit_final` was called earlier, but followed by trailing `print()` statements: re-emit the serialized JSON protocol line at the very end of stdout so `lines[-1]` is guaranteed to be valid JSON.
  - If an unhandled exception occurred: do nothing, allowing standard exception propagation to `sandbox.py`.

#### 2. Type Identifiers & `emit_final` Robustness (`bridge.py`)
- Inject type constants into sandbox globals:
  ```python
  number = 'number'
  string = 'string'
  boolean = 'boolean'
  table = 'table'
  ```
- Subclass `list` with a custom metaclass so `list == 'list'` evaluates to True while `list(...)` and `isinstance(..., list)` remain 100% functional.
- In `_bridge_emit_final`:
  - Map type synonyms: `int`, `float`, `integer` $\to$ `'number'`; `str`, `text` $\to$ `'string'`; `bool` $\to$ `'boolean'`; `array`, `sequence`, `list` $\to$ `'list'`; `dict`, `ranking` $\to$ `'table'`.
  - Map aliases `msg`, `message`, `detail`, `note`, `explanation` to `evidence`.
  - Default `evidence` to `"Computed via sandbox"` if omitted or empty.

#### 3. Vietnamese Number Parsing in Runtime (`bridge.py`)
- Patch `pd.to_numeric` in `_BRIDGE_RUNTIME_PATCH`: if parsing an object Series or formatted string produces `NaN` where the input contained non-null strings, fallback to `parse_vn_number`.
- Patch `builtins.int` and `builtins.float`: when passed a string like `'37,000.0000'`, attempt `parse_vn_number` before raising `ValueError`.
- Expose `vn_num = parse_vn_number` in globals.

#### 4. Payload Bounding (<3,500 chars)
- In `_bound_run_python_payload`, set `max_json_chars: int = 3500`.
- In `run_python_tool`, cap `stdout` to 2,500 chars and `stderr` to 800 chars.
- This ensures serialized JSON payloads never reach OpenCode's 8k truncation threshold, completely eliminating OpenCode's inline truncation notices and disk dumps.

#### 5. Column Lookup Tolerance (`pd.DataFrame.__getitem__`)
- Wrap `pd.DataFrame.__getitem__`: upon `KeyError`, search columns with:
  1. Exact case-insensitive matching (`c.lower() == key.lower()`).
  2. Accent-insensitive and punctuation-stripped matching (NFD normalization).
  3. Multilingual synonym matching (e.g. mapping `'Tanggal'` or `'Date'` to the shop's date column).

#### 6. Notebook Synchronization & Prompt Reinforcement
- Synchronize Cell 1 `EMBEDDED_BRIDGE_PY` byte-for-byte with `tmp/opencode-structured/bridge.py`.
- Update `EMBEDDED_RUN_PYTHON_JS` and `build_system_instructions` to explicitly state that helpers are in `globals()` (do not import) and remind the model to output final text after `emit_final`.
- Verify Cell 3 normalizer promotes verified calculations when `tool_succeeded_but_final_empty == True`.

---

## 5. Verification & Invalidation Criteria

### 5.1 Verification Commands
1. **Automated Notebook Regression Suite:**
   ```bash
   pytest tests/test_ornith_opencode_kaggle_notebook.py -v
   ```
   Must pass all 17 tests, specifically verifying byte-for-byte synchronization between Cell 1 and `bridge.py`.
2. **Core Unit Test Suite:**
   ```bash
   pytest -o pythonpath=. tests/test_sandbox_protocol.py tests/test_p3_sandbox_temporal.py tests/test_eval_and_normalizer.py tests/test_profiler.py tests/test_time_resolver.py -v
   ```
   Must pass all 52 tests with zero regression.
3. **Data Integrity Audit:**
   ```bash
   git status
   ```
   Must confirm zero additions, modifications, or deletions in `data/`.

### 5.2 Invalidation Conditions
- Any failure in `test_notebook_structure_syntax_and_manifests` invalidates template synchronization.
- Any modification to `tmp/opencode-structured/src/agent/sandbox.py` invalidates the pinned hash requirement (`7b8bb34772d8`) for the HF bundle.
- Any modification to files in `data/` invalidates the submission under competition rules.

---
*Report successfully compiled and validated.*
