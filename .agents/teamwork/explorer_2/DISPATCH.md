## 2026-11-13T05:03:35Z
Bạn là subagent teamwork_explorer được giao nhiệm vụ khảo sát Quy tắc nghiệp vụ (Rulebook) và cơ chế Thích ứng Luật Động (Dynamic In-Context Rule Generalization) cho dự án DataMate (Zalo AI Challenge 2026).

Đọc tài liệu yêu cầu gốc tại: d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\ORIGINAL_REQUEST.md
Thư mục làm việc: d:\PROJECT\ZALO-AI-CHALLENGE-2026
Thư mục trạng thái của bạn: d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\explorer_2

Nhiệm vụ cụ thể:
1. Đọc và phân tích kỹ các tài liệu trong `docs/` (`description.md`, `data.md`, `evaluation.md`, `rule.md`) và các file `rulebook.md`, `calendar.csv` trong `data/`:
   - Phân tích chi tiết Rulebook §2: Quy tắc phân giải mốc thời gian tương đối (hôm nay, hôm qua, tuần này, tháng trước, quý này, cùng kỳ năm ngoái...) kết hợp tra cứu lịch âm/Tết, ngày nghỉ từ `calendar.csv`.
   - Phân tích chi tiết Rulebook §7: Tiêu chí xác định câu hỏi ngoài phạm vi dữ liệu hoặc không đủ căn cứ để trả lời; các trường hợp bắt buộc phải trả về `"abstain"` (câu hỏi về tương lai, câu hỏi thiếu dữ kiện, trường dữ liệu không tồn tại...).
   - Phân tích chi tiết Rulebook §8: Quy tắc khử trùng lặp đơn hàng / dòng chi tiết đơn hàng (order deduplication).
2. Khảo sát cấu trúc các gói dữ liệu và file `README.md` của các shop trong `data/train/` (các ngành hiện có: nhà thuốc, cà phê, tạp hóa...) và `data/public_test/` (3 ngành mới xuất hiện):
   - So sánh sự khác biệt về quy ước kinh doanh, tên cột, cấu trúc bảng giữa các ngành.
   - Phân tích thách thức: Trong Private Test sẽ xuất hiện các ngành nghề hoàn toàn mới lạ chưa từng có trong Train.
   - Đề xuất cơ chế Dynamic In-Context Rule Extraction: Cách trích xuất luật động từ `rulebook.md` (qua `shared_context`) và `README.md` của shop runtime để đưa vào prompt cho mô hình Qwen2.5-14B-Instruct-1M; nếu khái niệm trong câu hỏi không thể map với bất kỳ bảng/cột nào trong data hay luật trong `README.md`, kích hoạt Rulebook §7 để trả về `"abstain"`.
3. Xuất báo cáo chi tiết vào:
   `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\explorer_2\report.md`
   và tạo file `handoff.md` theo Handoff Protocol.
4. Gửi tin nhắn hoàn thành về cho orchestrator qua send_message.
LƯU Ý: Tuyệt đối CHỈ ĐỌC, KHÔNG chỉnh sửa bất kỳ file mã nguồn nào trong `src/` hay `notebooks/`!
