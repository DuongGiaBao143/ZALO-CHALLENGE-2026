# CLAUDE.md — DataMate (Zalo AI Challenge 2026)

Đọc `AGENTS.md` trước (quy tắc bất khả xâm phạm). File này là trạng thái THỰC TẾ hiện tại.

## Cảnh báo: tài liệu cũ lệch thực tế
`README.md`, `HANDOFF_PLAN.md`, `.agents/PROJECT_MEMORY.md` mô tả Qwen2.5-14B + vLLM + ReAct trong `src/agent/solver.py`. Pipeline đang chạy thật khác:
- Harness **opencode** + model **Ornith 1.5 9B** chạy qua Ollama, đánh giá trên **Kaggle 2xT4**.
- Code chạy thật: `submission/inference/agent_runner.py` (+ `submission/runtime/`: `src/agent/sandbox.py`, `tools/run_python.js`, ...). Notebook eval `notebooks/Evaluate_Ornith_OpenCode_Kaggle_2T4.ipynb` **nhúng bản sao** agent_runner ở cell 3. Sửa runner thì phải sửa cả hai chỗ.
- Cấu hình eval (theo test): 600s/câu, MAX_STEPS_EVAL_AGENT=14, NUM_CTX=65536, MAX_OUTPUT_TOKENS=4096, run_python timeout 90s.

## Luật
- `data/` read-only. Rulebook: `data/train/rulebook.md`. Điểm: đúng +1, sai −1, abstain 0, nên thà abstain còn hơn đoán.
- Gold: `eval_gold/unseen_gold_50.jsonl`. Trace eval: `traces/*.json`.

## Kết quả eval gần nhất (unseen_50, 41/50 câu có trace)
10 đúng, 4 sai, 27 abstain (PA ≈ 0.146). Phân tích từng câu: `docs/trace_failure_analysis_unseen50.md`.
Nguyên nhân chính: 19 câu timeout (model chậm, 51% lần run_python lỗi), 4 câu sai logic dữ liệu, 3 câu đúng bị abstain oan do gate.

## Đã làm (chưa chạy lại trên Kaggle)
Bản vá trong `normalize_final_answer` (agent_runner.py + notebook cell 3): cứu final `unanswerable`/`date`/`string` khi final text không parse được; loại final string dạng `{...}`/`[...]`. Test: `tests/test_ornith_opencode_kaggle_notebook.py` (thêm `test_unparseable_final_rescues_...`), 33 test pass. Replay trên trace cũ: 4 -> 8 điểm. Bản gốc: `tmp/agent_runner.py.bak`, `tmp/notebook.ipynb.bak`; script replay `tmp/replay.py`.

## Việc tiếp theo (theo ưu tiên)
1. Sửa 4 câu sai logic (đang gây −1):
   - 5ade: không lọc trạng thái, parse "1tr150" thành 1150 thay vì 1.150.000.
   - 5c5f: lọc ngày `str[:7]=="2025-10"` trên ngày DD/MM/YYYY nên ra 0; trạng thái "Đang giao dịch" không khớp.
   - 6a54: không quy đổi đơn vị qua DanhSachQuyDoi, emit_final hai lần.
   - 0c20: emit_final hard-code số từ output cũ (đã được gate chặn thành abstain).
   Hướng: prompt/helper bắt dùng `load_clean_df`, chuẩn hoá trạng thái/ngày/tiền, quy đổi đơn vị.
2. Giảm timeout: cắt lỗi run_python (KeyError cột, import bịa `tools.parse`/`helpers.emit`), cân nhắc emit sớm khi obs đã có đáp án (80f4, 1b11).
3. 338a, 3b5c dừng với `finish_reason=length`, chưa rõ nguyên nhân.
4. Trước khi upload bundle: `scripts/upload_ornith_opencode_hf_bundle.py` ghim hash sandbox.py (chưa đụng); kiểm tra bundle có chứa agent_runner.py mới.

## Chạy test
`python -m pytest tests/ -q` (test notebook mất ~95s). Cần cài pytest.

## Agent skills

### Issue tracker

Issues and specs are local markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), recorded as a `Status:` line in each issue file. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
