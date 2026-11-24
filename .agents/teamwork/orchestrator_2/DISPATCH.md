## 2026-11-11T18:29:47Z

Hoàn thiện và sửa chữa 3 thành phần P1, P2, P3 trong pipeline hỏi đáp DataMate (Zalo AI Challenge 2026) cho môi trường thi đấu chính thức, đảm bảo tối đa hóa điểm Penalized Accuracy (PA), chống tràn context và bảo toàn dữ liệu thô.

Working directory: d:\PROJECT\ZALO-AI-CHALLENGE-2026
Integrity mode: demo
The team must NOT:
- Đọc mã nguồn test để biết trước hành vi mong đợi trước khi lập trình.
- Chỉnh sửa hoặc làm biến đổi bất kỳ file dữ liệu nào trong thư mục `data/` (dữ liệu train/test là strictly read-only).
- Vi phạm thể lệ cuộc thi Zalo AI Challenge (không gọi API ngoài, tổng mô hình <= 15B tham số, tương thích phần cứng 2x RTX 5090).

## Requirements

### R1. P1 — Sửa Step 1 trong `business_loader.py` (Schema profiling & Value inspection)
Không giới hạn 200 dòng khi quét các cột trạng thái/danh mục có ít giá trị duy nhất; thực hiện quét toàn bộ dữ liệu trong bộ nhớ (RAM), báo rõ `unique_count` và tách biệt hoàn toàn giữa danh sách toàn bộ nhãn thực tế (đối với cột ít giá trị) với mẫu dữ liệu tham khảo có chú thích (đối với cột nhiều giá trị). Thiết kế cơ chế chống tràn context linh hoạt phù hợp với context window 16k của mô hình: thiết lập trần cứng (capping) số lượng nhãn và dung lượng block schema, tự động gộp nhóm các sheet có cùng cấu trúc, và áp dụng lấy top tần suất / observation cho các cột dữ liệu bẩn nhiều nhãn.

### R2. P2 — Bật và vá Step 3 trong `solver.py` (Core rules & Zero handling)
Kích hoạt `eval_core_rules` trong Step 3. Điều chỉnh quy tắc kiểm tra kết quả `0` để chấp nhận đáp án số `0` khi có bằng chứng/check hợp lệ từ môi trường thực thi sandbox. Bổ sung cơ chế phát hiện và chặn các mẫu lỗi hallucination phổ biến (`[0, 0]`, bảng công nợ toàn số `0`, danh sách xếp hạng top-k trùng lặp). Kết nối luồng xử lý thất bại hoặc lỗi thực thi không giải quyết được sang Abstain Gate khi đã vượt quá số lần retry tối đa.

### R3. P3 — Xử lý điểm mù ngoài 3 bước (Sandbox unmerge & Temporal resolution)
Bổ sung hàm helper trong `src/agent/sandbox.py` để xử lý các bảng Excel có ô bị gộp (merged cells) thông qua cơ chế unmerge và điền giá trị lan truyền (`ffill`). Cập nhật `build_user_prompt` trong `src/agent/prompts.py` và module xử lý thời gian `src/time_resolver/calendar_utils.py` để nhận diện chính xác và phân giải đúng khoảng thời gian cho cụm từ tương đối "cùng kỳ tháng trước".

### R4. Ràng buộc an toàn dữ liệu và tuân thủ thể lệ thi đấu
Toàn bộ dữ liệu trong thư mục `data/` (`data/train/`, `data/public_test/`, các thư mục con `biz_xxx/`, `dev_xxx/`, file `calendar.csv`, `rulebook.md`,...) là strictly read-only; tuyệt đối không chỉnh sửa, đổi tên, ghi đè hoặc xóa bất kỳ file nào. Toàn bộ giải pháp phải vận hành độc lập offline (`--network none`) và tuân thủ giới hạn mô hình <= 15B tham số theo thể lệ cuộc thi Zalo AI Challenge 2026.

## Acceptance Criteria

### Verification
- [ ] Có bộ unit tests tự động độc lập trong thư mục `tests/` kiểm thử đầy đủ các chức năng mới của P1 (quét đầy đủ nhãn, capping trần context), P2 (chấp nhận 0 có check, chặn `[0, 0]`, bảng nợ 0, ranking trùng lặp, chuyển abstain khi hết retry), P3 (helper unmerge/ffill trong sandbox, phân giải cụm "cùng kỳ tháng trước").
- [ ] Chạy kiểm thử đối chiếu thành công trên các câu hỏi dev mẫu bị lỗi từ báo cáo `failure_analysis.md` (tại `result/qwen25_14b_1m_code_only_rulebook_20261111_155610/eval_dev_30_colab_a100_40gb_ctx16384/failure_analysis.md`), xác nhận kết quả được cải thiện đúng kỳ vọng và không gây hồi quy (regression).

### Implementation Quality
- [ ] `business_loader.py` quét toàn bộ dữ liệu trong RAM trích xuất đủ nhãn cho cột ít giá trị mà không bị giới hạn 200 dòng, đồng thời đảm bảo schema block không vượt trần token an toàn.
- [ ] Các sheet trùng schema được gộp nhóm gọn; cột nhiều nhãn/bẩn hiển thị top tần suất kèm chú thích mẫu.
- [ ] `solver.py` chấp nhận kết quả 0 hợp lệ có check và chặn đúng các mẫu hallucination; tự động fallback về `abstain` khi hết retry.
- [ ] Helper unmerge/ffill trong `sandbox.py` xử lý chính xác dữ liệu bảng Excel merge cell.
- [ ] Cụm từ "cùng kỳ tháng trước" được phân giải ra đúng mốc ngày bắt đầu và kết thúc tham chiếu.
- [ ] Toàn bộ file và thư mục trong `data/` được giữ nguyên vẹn 100%, không bị sửa đổi hay ghi đè.


## 2026-11-12T05:39:00Z

[System Recovery Wakeup] Server vừa khởi động lại. Tiến trình của bạn đã được kiểm tra:
Theo progress.md và GATE_STATUS.md của bạn, Iteration 1 đã hoàn thành (83/83 tests passed, Forensic Audit CLEAN). Vòng review đối kháng của Reviewers và Challenger 1 đã đưa ra 3 khuyến nghị biên cụ thể:
1. Đặt mặc định `header=0` cho `load_excel_unmerge` trong `src/agent/sandbox.py`.
2. Chống rò rỉ lan truyền (ffill leakage) giữa các nhóm dữ liệu trong bảng unmerged khi không có parent identifier rõ ràng.
3. Chuẩn hóa parse dữ liệu chuỗi số tiền (ví dụ có dấu phẩy/chấm phân cách nghìn) trong guardrail bảng nợ của `src/agent/solver.py`.

Xin hãy tiếp tục quy trình Iteration 2: dispatch worker_2 thực hiện các sửa chữa biên trên, chạy lại kiểm thử độc lập và vòng review/challenger/forensic auditor, bảo toàn 100% thư mục data/, và claim victory khi đạt GATE PASS.
