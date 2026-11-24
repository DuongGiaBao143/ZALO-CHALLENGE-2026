## 2026-11-12T05:53:32Z

You are replacing worker_2 to implement the exact edge-case fixes requested in Iteration 1 review.
Read:
1. `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\reviewer_2\handoff.md`
2. `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\challenger_1\handoff.md`
3. `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\orchestrator_2\GATE_STATUS.md`

TASKS:
1. Sửa `src/agent/sandbox.py`:
   - Trong hàm `unmerge_and_ffill` (khoảng dòng 127) VÀ bên trong chuỗi `_SANDBOX_RUNTIME_HELPERS` (khoảng dòng 597):
     Đổi `else:` thành `elif not detected_id:`.
     (Lý do: Khi bảng unmerged đã có đủ mã đơn, không được chạy fallback ffill đè tên khách của đơn trước lên khách lẻ None).
   - Trong hàm `load_excel_unmerge` (khoảng dòng 180) VÀ bên trong chuỗi `_SANDBOX_RUNTIME_HELPERS` (khoảng dòng 650):
     Đổi giá trị mặc định của tham số `header: Any = 0` (hiện đang là `header: Any = None`).
2. Sửa `src/agent/solver.py`:
   - Trong `_eval_guard_issue`:
     - Pattern 2 (Debt table check): Khi duyệt qua các dòng để kiểm tra số tiền nợ có > 0 không, cần parse chuỗi số an toàn (bỏ dấu phẩy phân cách nghìn và convert sang float: `float(str(r[idx]).replace(',', '').strip()) > 0`) để bảng công nợ chứa chuỗi số dương (như '150000' hay '150,000') không bị chặn nhầm.
     - Pattern 1 (`[0, 0]`): Bắt thêm trường hợp chuỗi số 0 (như `all(str(x).strip() in ('0', '0.0', '0,0') for x in answer)`).
3. Sửa `src/profiler/business_loader.py`:
   - Thêm `"khachhang"`, `"khach"` vào set `_EXCLUDED_VALUE_COLUMNS`.
4. Bổ sung Unit Tests & Chạy Test:
   - Trong `tests/test_p3_sandbox_temporal.py`: thêm `test_unmerge_and_ffill_unmerged_table_no_leakage` và `test_load_excel_unmerge_default_header`.
   - Trong `tests/test_p2_solver_guardrails.py`: thêm test cho bảng nợ có chuỗi số dương và danh sách chuỗi 0 `['0', '0']`.
   - Chạy toàn bộ test: `python -m pytest tests/test_*.py -v` (đảm bảo 100% passed).
   - Kiểm tra `git status data/` (đảm bảo sạch 100%).

OUTPUT:
Ghi báo cáo đầy đủ vào:
`d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\worker_3\handoff.md`
Sau đó gọi send_message báo hoàn thành.


## 2026-11-12T06:08:42Z
**Context**: Iteration 2 Edge Case Refinements
**Content**: Status check on pytest execution. How are the test runs looking?
**Action**: Please update progress.md and send a brief status report.
