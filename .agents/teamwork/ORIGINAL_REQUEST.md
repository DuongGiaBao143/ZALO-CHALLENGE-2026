# Original User Request

## Initial Request — 2026-11-13T05:01:55Z

Soạn thảo tài liệu kế hoạch bàn giao kỹ thuật (HANDOFF_PLAN.md) tại thư mục gốc repository, đặc tả kiến trúc tinh gọn 6 công cụ phi ngành nghề (Domain-Agnostic Lean Helpers) cho agent trong dự án DataMate (Zalo AI Challenge 2026), giao thức suy luận ReAct với Ephemeral Thinking và khả năng thích ứng luật động cho mô hình Qwen/Qwen2.5-14B-Instruct-1M, cơ chế cổng Abstain-First triệt tiêu điểm phạt PA, cùng hướng dẫn chạy Colab và tinh chỉnh LoRA, sau đó commit và push tài liệu lên nhánh giabao trên GitHub của nhóm.

Integrity mode: development

## Requirements

### R1. Soạn thảo Tài liệu Kế hoạch Bàn giao Kỹ thuật (HANDOFF_PLAN.md)
Tạo file `HANDOFF_PLAN.md` tại thư mục gốc repository đóng vai trò tài liệu kỹ thuật toàn diện để bàn giao cho lập trình viên phụ trách triển khai, bao gồm:
1. **Đặc tả Bộ 6 Công cụ Tinh gọn Phi Ngành Nghề (Domain-Agnostic Lean Helpers) trong Sandbox (`src/agent/sandbox.py`):**
   - Loại bỏ các thiết kế tool cồng kềnh, phân tán hoặc gán cứng logic theo ngành nghề (hardcoded domain logic); thiết kế 6 helper cốt lõi thuần túy dựa trên các phép toán bảng biểu/văn bản tổng quát (generic tabular/text primitives):
     - `explore_data(file, column=None, keyword=None, n=5)`: Khám phá tổng hợp cấu trúc bảng, kiểu dữ liệu, độ bao phủ thời gian `[min_date, max_date]`, và đếm giá trị độc nhất.
     - `fuzzy_find(df_or_file, column, query, top_k=5)`: Tìm kiếm mờ tiếng Việt xóa dấu (`vn_norm`) cho tên sản phẩm/khách hàng viết tắt hoặc sai chính tả.
     - `load_clean_df(file, sheet=0, dedup_order=True, as_of_date=None)`: Đọc bảng tự động unmerge, dò header, khử trùng lặp dòng nội bộ đơn hàng (Rulebook §8), và lọc bản ghi theo `as_of_date`.
     - `resolve_date(expr, as_of_date)`: Phân giải biểu thức thời gian tương đối theo Rulebook §2 kết hợp tra cứu lịch âm/Tết từ `calendar.csv`.
     - `emit_obs(data, msg)`: Xuất kết quả quan sát chuẩn hóa giữa các turn, tự động làm sạch NaN và giới hạn độ dài 4.000 ký tự.
     - `emit_final(answer, type, evidence, check=None, reason=None)`: Xuất câu trả lời cuối cùng tuân thủ giao thức BTC kèm cơ chế tự động sanity check tính hợp lý.
   - Mỗi công cụ phải có mô tả mục đích kỹ thuật, chữ ký hàm (signature), kiểu dữ liệu tham số, kết quả trả về, xử lý biên và mã mẫu/mã giả hướng dẫn cài đặt.
2. **Giao thức Suy luận ReAct, Ephemeral Thinking & Thích ứng Luật Động (Dynamic Rule Generalization):**
   - Đặc tả quy trình suy luận ngắn gọn (3-5 dòng `Thought:` định hướng mục tiêu con, lập kế hoạch gọi helper trước khi sinh code).
   - Cơ chế "Ephemeral Thinking": lược bỏ các khối `<think>` thô của các turn trước khi xây dựng ngữ cảnh cho Turn 2+ (chỉ lưu giữ tóm tắt 3-5 dòng kế hoạch/trạng thái + code + observation) để bảo toàn context window trong giới hạn `max_model_len=16384`.
   - Cơ chế trích xuất luật động trong ngữ cảnh (Dynamic In-Context Rule Extraction): giải quyết bài toán biến động ngành nghề giữa Train (3 ngành), Public Test (thêm 3 ngành mới) và Private Test (các ngành chưa từng xuất hiện). Agent phải đọc `rulebook.md` (qua `shared_context`) và `README.md` của từng shop khi chạy để tự động suy diễn quy tắc riêng; nếu khái niệm ngành trong câu hỏi hoàn toàn không có căn cứ trong dữ liệu hoặc rulebook runtime, bắt buộc áp dụng Rulebook §7 để kích hoạt cổng Abstain thay vì suy đoán sai lệch.
3. **Cơ chế Cổng Abstain-First & Xử lý Lỗi Thực nghiệm (Khắc phục Điểm Phạt PA):**
   - Phân tích nguyên nhân gốc rễ của 9-12 câu trả lời sai trên bộ 30 Dev benchmark (PA -0.1667 base, -0.0667 LoRA).
   - Thiết kế các cổng kiểm duyệt bắt buộc: chặn bẫy lọc rỗng (empty filter trap), câu hỏi ngoài phạm vi dữ liệu (Rulebook §7), và kết quả 0 chưa được kiểm chứng, tự động chuyển đổi các câu có độ tin cậy thấp sang `"abstain"` (0 điểm) để triệt tiêu hình phạt -1.0 điểm.
4. **Hướng dẫn Đánh giá Colab và Tinh chỉnh LoRA cho Qwen2.5-14B-Instruct-1M:**
   - Giữ nguyên mô hình baseline `Qwen/Qwen2.5-14B-Instruct-1M` (14.7B <= 15B, tuân thủ Rule 2 của cuộc thi, tương thích hoàn toàn hạ tầng vLLM và Docker).
   - Hướng dẫn cụ thể các bước chạy đánh giá trên Colab qua notebook `notebooks/Evaluate_Qwen25_14B_1M_Colab_G4.ipynb` với pipeline helper mới.
   - Cảnh báo rõ ràng việc không tiếp tục dùng dataset SFT cũ chỉ chứa code; hướng dẫn chuẩn hóa định dạng dữ liệu huấn luyện LoRA kết hợp chuỗi suy luận ReAct và quỹ đạo gọi helper tinh gọn.

### R2. Phạm vi Công việc và Ranh giới (Scope Boundaries)
Chỉ thực hiện tạo và hoàn thiện file tài liệu `HANDOFF_PLAN.md`; tuyệt đối không chỉnh sửa trực tiếp mã nguồn trong `src/` hoặc các notebook trong `notebooks/`. Toàn bộ công việc viết code và chỉnh sửa notebook sẽ do lập trình viên nhận bàn giao thực hiện dựa trên tài liệu này.

### R3. Commit và Push Tài liệu lên GitHub
Commit file `HANDOFF_PLAN.md` với thông điệp rõ ràng và push lên repository GitHub của nhóm (`Thinh-gitgood/ZALO-AI-CHALLENGE-2026`) tại nhánh `giabao`.
