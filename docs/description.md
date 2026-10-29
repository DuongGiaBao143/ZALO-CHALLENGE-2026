# Zalo AI Challenge — DataMate: Mô tả bài toán

## Tổng quan (Overview)

Bảng tính (*spreadsheets*) và các cơ sở dữ liệu (*databases*) đơn giản là những hệ thống lưu trữ dữ liệu được sử dụng rộng rãi nhất trên thế giới. Một chủ cửa hàng lưu doanh thu và tồn kho trong Excel; một giáo viên lưu điểm số và điểm danh; một phòng khám lưu lịch sử khám bệnh và các lô thuốc; một nhân viên nhân sự (HR) lưu bảng chấm công; một hợp tác xã lưu sản lượng và chi phí đầu vào; một ủy ban xã lưu thống kê hộ gia đình; một nhà báo tải dữ liệu mở từ Tổng cục Thống kê; một nhân viên trong công ty lớn muốn lấy một con số từ kho dữ liệu (*data warehouse*) mà không cần phải chờ đội ngũ dữ liệu (*data team*). Tất cả họ đều có dữ liệu, nhưng hầu như không ai trong số họ biết viết câu truy vấn (*query*). Điều họ mong muốn là có thể hỏi trực tiếp bằng tiếng Việt tự nhiên — *“Tháng này bán chạy nhất mặt hàng gì?”*, *“Tuần rồi bán được bao nhiêu ly trà sữa?”*, *“Còn ai nợ tiền chưa trả?”*, *“Thuốc nào sắp hết hạn trong kho?”* — và nhận được câu trả lời chính xác.

**DataMate** đặt ra thử thách xây dựng một **AI agent** có khả năng trả lời các câu hỏi tiếng Việt bằng ngôn ngữ tự nhiên trực tiếp trên dữ liệu có cấu trúc (*structured data*: CSV, Excel, SQLite): khi được cung cấp các file dữ liệu thô (*raw files*) và một câu hỏi, agent sẽ trả về câu trả lời chính xác — hoặc từ chối trả lời khi dữ liệu không đủ cơ sở để giải đáp câu hỏi đó. Dữ liệu của cuộc thi gắn liền với bối cảnh thực tế của các hộ kinh doanh và doanh nghiệp nhỏ tại Việt Nam — nhóm người dùng bảng tính lớn nhất cả nước với nguồn dữ liệu thực tế phong phú nhưng cũng lộn xộn (*messy*) nhất — tuy nhiên, năng lực cốt lõi mà bạn xây dựng mang tính tổng quát: **Hỏi đáp bằng ngôn ngữ tự nhiên trên dữ liệu dạng bảng (*Natural-language Question Answering over Tabular Data*)**.

---

## Đầu vào (Input)

- **Gói dữ liệu (*data package*) của một doanh nghiệp/hộ kinh doanh (`business`):** Bao gồm một hoặc nhiều file (`.csv`, `.xlsx`, `.sqlite`) kèm theo một file `README.md` ngắn gọn mô tả về doanh nghiệp đó.
- **Câu hỏi (`question`):** Một câu hỏi được diễn đạt bằng tiếng Việt đời thường.
- **Ngày mốc tham chiếu (`as_of_date`):** Mốc thời gian đóng vai trò là ngày “hôm nay” (*today*), dùng làm căn cứ để phân giải các biểu thức thời gian tương đối (ví dụ: *“tháng này”*, *“tuần rồi”*, *“cùng kỳ năm ngoái”*).
- **Bộ quy tắc (`rulebook`) và lịch Âm – Dương (`solar–lunar calendar`):** Được dùng chung cho mọi doanh nghiệp trong cùng một tập dữ liệu (*split*) (xem chi tiết tại phần *Data*).

---

## Đầu ra (Output)

- Một câu trả lời cuối cùng thuộc một trong các kiểu (`type`) được quy định trong phần *Evaluation*:
  - Một giá trị cụ thể (*value*): `number`, `percent`, `string`, `date`, `boolean`, `list`, `table`.
  - `unanswerable`: Khi dữ liệu không thể hỗ trợ trả lời câu hỏi.
  - `abstain`: Khi agent chủ động lựa chọn không trả lời.

---

## Ví dụ (Example)

**Input** — một dòng trong file `questions.jsonl`:

```json
{"id": "q_06de33fa21cc", "business_id": "biz_118", "question": "sp bán dc nhiều nhất tuần rồi là gì", "as_of_date": "2026-03-04"}
```

**Output** — một dòng trong file `submission.jsonl`:

```json
{"id": "q_06de33fa21cc", "type": "string", "answer": "Xi măng Hà Tiên PCB40 bao 50kg"}
```
