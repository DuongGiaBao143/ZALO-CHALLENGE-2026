## 2026-11-13T05:03:47Z
Bạn là subagent teamwork_explorer được giao nhiệm vụ khảo sát kết quả thực nghiệm Dev Benchmark (30 câu hỏi) và môi trường đánh giá Colab / huấn luyện LoRA cho mô hình Qwen/Qwen2.5-14B-Instruct-1M của dự án DataMate (Zalo AI Challenge 2026).

Đọc tài liệu yêu cầu gốc tại: d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\ORIGINAL_REQUEST.md
Thư mục làm việc: d:\PROJECT\ZALO-AI-CHALLENGE-2026
Thư mục trạng thái của bạn: d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\explorer_3

Nhiệm vụ cụ thể:
1. Khảo sát dữ liệu thực nghiệm và kết quả benchmark trên bộ 30 câu Dev (tìm trong `result/`, `data/train/`, `scripts/`, `tests/` hoặc các file log kết quả):
   - Phân tích nguyên nhân gốc rễ của 9-12 câu trả lời sai trên bộ 30 Dev benchmark (PA score: base model -0.1667, LoRA model -0.0667).
   - Xác định các mẫu lỗi điển hình:
     + Bẫy lọc rỗng (empty filter trap): truy vấn điều kiện không khớp -> DataFrame rỗng -> sinh kết quả sai/None/0 thay vì nhận diện dữ liệu không có hoặc tìm kiếm mờ.
     + Sai lệch tên sản phẩm/khách hàng do viết tắt, thiếu dấu tiếng Việt.
     + Kết quả 0 chưa được kiểm chứng (zero unverified): trả về 0 khi thực tế là không có dữ liệu để tính toán.
     + Câu hỏi ngoài phạm vi (out of scope) nhưng mô hình hallucinate đáp án thay vì trả về `"abstain"`, dẫn đến bị phạt -1.0 điểm theo công thức PA.
   - Thiết kế các cổng kiểm duyệt (Abstain-First Gate) để chặn đứng các bẫy này và chuyển đổi sang `"abstain"` (lấy 0 điểm an toàn).
2. Khảo sát notebook đánh giá trên Google Colab `notebooks/Evaluate_Qwen25_14B_1M_Colab_G4.ipynb`:
   - Phân tích quy trình cài đặt môi trường, tải mô hình `Qwen/Qwen2.5-14B-Instruct-1M` (14.7B params, tuân thủ Rule 2 <= 15B), cấu hình vLLM, tham số suy luận (seed=42, temperature=0.0).
   - Các bước nạp dữ liệu câu hỏi, chạy batch suy luận với sandbox/solver, xuất file kết quả `submission.jsonl` và logs.
   - Hướng dẫn cụ thể cách tích hợp bộ 6 Lean Helper mới vào notebook này.
3. Khảo sát định dạng dữ liệu huấn luyện LoRA:
   - Tại sao dataset SFT cũ chỉ chứa code thuần túy lại không đạt hiệu quả cao hoặc gây ảo giác?
   - Định dạng chuẩn hóa mới cho dataset SFT kết hợp chuỗi suy luận ReAct (`Thought:`) định hướng mục tiêu con và quỹ đạo gọi helper tinh gọn (`Action:`, `Observation:`, `emit_final`).
4. Xuất báo cáo chi tiết vào:
   `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\explorer_3\report.md`
   và tạo file `handoff.md` theo Handoff Protocol.
5. Gửi tin nhắn hoàn thành về cho orchestrator qua send_message.
LƯU Ý: Tuyệt đối CHỈ ĐỌC, KHÔNG chỉnh sửa bất kỳ file mã nguồn nào trong `src/` hay `notebooks/`!
