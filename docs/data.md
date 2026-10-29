# Zalo AI Challenge 2026 — DataMate: Mô tả Dữ liệu & Định dạng Nộp bài (Data & Submission Format)

## 1. Các loại hình kinh doanh (Business types)

Bộ dữ liệu bao phủ nhiều loại hình hộ kinh doanh và doanh nghiệp nhỏ phổ biến tại Việt Nam: cửa hàng tạp hóa (*grocery stores*), quán cà phê và trà sữa (*coffee and bubble-tea shops*), nhà hàng/quán ăn (*restaurants*), nhà thuốc (*pharmacies*), cửa hàng vật liệu xây dựng (*building-material stores*), tiệm sửa xe máy (*motorbike repair shops*), cửa hàng mẹ và bé (*mother-and-baby stores*), v.v.
- Tập kiểm tra riêng tư (**Private test**) sẽ bao gồm cả những loại hình kinh doanh **chưa từng xuất hiện** trong tập huấn luyện (*training*) hoặc tập kiểm tra công khai (*public test*).
- Mỗi doanh nghiệp chứa dữ liệu hoạt động kéo dài từ **12 – 30 tháng** mang tính mùa vụ rõ rệt (Tết Nguyên Đán, Tết Trung thu, các ngày lễ, ngày nhận lương, cuối tuần) với quy mô từ vài trăm dòng cho đến khoảng **300.000 dòng (*rows*)**.

---

## 2. Cấu trúc gói dữ liệu (Package structure)

```text
<split>/
├── data/<business_id>/
│   ├── *.csv | *.xlsx | *.sqlite        # một hoặc nhiều file dữ liệu
│   └── README.md                        # mô tả và ghi chú về doanh nghiệp
├── rulebook.md                          # bộ quy tắc và từ vựng mặc định
├── calendar.csv                         # lịch Dương – Âm (phục vụ tính dịp Tết, ngày âm)
├── questions.jsonl                      # mỗi dòng là một câu hỏi
└── answers.jsonl                        # chỉ có ở tập training (đáp án chuẩn)
```

### Ví dụ một bản ghi trong `questions.jsonl`:

```json
{"id": "q_01234", "business_id": "biz_017", "question": "thang nay hang nao ban cham nhat, ton nhieu ma ban ko dc", "as_of_date": "2026-08-27"}
```

- Các doanh nghiệp trong tập **Training** đi kèm thêm file `answers.jsonl` chứa đáp án chuẩn (*reference answer*) cho mọi câu hỏi huấn luyện, được liên kết qua trường `"id"`.
- Mỗi dòng trong `answers.jsonl` tuân theo đúng định dạng nộp bài, cộng thêm trường `"alias"` liệt kê các dạng được chấp nhận khác của câu trả lời dạng tên gọi (bao gồm các cách viết khác xuất hiện trong dữ liệu và mã sản phẩm/đối tượng — *item code*).
- Các câu hỏi không thể trả lời (`unanswerable`) có `"answer": null`.
- File nộp bài (`submission.jsonl`) của đội thi **không cần** có trường `"alias"`.

### Ví dụ một bản ghi trong `answers.jsonl` (đáp án chuẩn của câu hỏi ví dụ ở phần Description):

```json
{"id": "q_06de33fa21cc", "type": "string", "answer": "Xi măng Hà Tiên PCB40 bao 50kg", "alias": ["SP0001"]}
```

> **Lưu ý về chất lượng `README.md`:** Chất lượng file `README.md` của từng doanh nghiệp không đồng đều: một số doanh nghiệp có từ điển dữ liệu (*data dictionary*) đầy đủ, một số khác chỉ có vài dòng ghi chú viết vội, và một số gần như không có thông tin gì.

---

## 3. Phân chia các tập dữ liệu (Splits)

| Tập dữ liệu (`Split`) | Số lượng doanh nghiệp (`Businesses`) | Số lượng câu hỏi (`Questions`) | Đáp án chuẩn (`Reference answers`) |
| :--- | :--- | :--- | :--- |
| **`Training`** | `30` | `~3.000` | Có (`Yes` — trong file `answers.jsonl`) |
| **`Public test`** | `10 – 20` | `~1.000` | Ẩn (*Hidden*); được chấm điểm trên bảng xếp hạng công khai (*public leaderboard*) |
| **`Private test`** | `10 – 20` | `~500` | Ẩn (*Hidden*); được công bố ở giai đoạn *private test*; bao gồm các loại hình kinh doanh mới |

---

## 4. Quy tắc nghiệp vụ & Cách hiểu mặc định (Business rules — Default interpretations)

Mỗi tập dữ liệu (`split`) đi kèm một file bộ quy tắc riêng (`rulebook.md`), quy định ý nghĩa mặc định của các thuật ngữ thông dụng khi câu hỏi không nêu cụ thể khác đi.
> **Cực kỳ quan trọng:** Nội dung `rulebook.md` **có thể thay đổi giữa các `split`**, vì vậy *agent* của bạn bắt buộc phải **đọc và áp dụng trực tiếp `rulebook.md` của chính `split` đang trả lời**, tuyệt đối không dùng bản sao cố định của `rulebook.md` từ tập *training*.

**Một số quy tắc điển hình (*Typical rules*):**
- **Doanh thu (`revenue`):** Tổng thành tiền của các dòng hàng (*sum of line amounts*) sau khi đã trừ chiết khấu theo từng dòng (*line-level discounts*) — **không** trừ voucher cấp độ toàn đơn hàng (*order-level vouchers*); **không** bao gồm thuế VAT và phí giao hàng (*delivery fees*); **loại trừ** các đơn hàng đã hủy (*cancelled orders*) và các đơn hàng có bất kỳ mặt hàng nào bị trả lại (*orders with any returned item*).
- **“Bán chạy”:** Tính theo **số lượng bán (*by quantity*)**.
- **Một tuần (*week*):** Tính từ **Thứ Hai đến Chủ Nhật (*Monday–Sunday*)**.
- **“Tháng này”:** Tháng chứa ngày mốc `as_of_date`, tính từ đầu tháng **đến hết ngày `as_of_date` đó** (*month-to-date up to and including `as_of_date`*).
- **Giá vốn mặc định (`default cost`):** Giá nhập bình quân gia quyền theo lô (*weighted-average purchase cost by lot*).
- **Khung thời gian dịp Tết (`Tết window`):** Từ **23 tháng Chạp đến hết mùng 10 Tết** (theo lịch Âm — *lunar calendar*).

---

## 5. Định dạng nộp bài (Submission format)

### 5.1. File kết quả (`submission.jsonl`)
Trong cả hai vòng thi, bạn tải lên một file `submission.jsonl`, mỗi dòng là một đối tượng JSON hợp lệ:

```json
{"id": "q_01234", "type": "string",  "answer": "Sting dâu 330ml"}
{"id": "q_01235", "type": "number",  "answer": 48250000}
{"id": "q_01236", "type": "percent", "answer": -12.45}
{"id": "q_01237", "type": "date",    "answer": "2026-08-15"}
{"id": "q_01238", "type": "boolean", "answer": true}
{"id": "q_01239", "type": "list",    "answer": ["Cà phê sữa", "Bạc xỉu", "Trà đào"]}
{"id": "q_01240", "type": "table",   "answer": {"columns": ["khach_hang", "so_tien_no"], "rows": [["Chị Lan", 3200000], ["Anh Tú", 1500000]]}}
{"id": "q_01241", "type": "unanswerable", "reason": "Dữ liệu không có giá vốn nên không tính được lợi nhuận"}
{"id": "q_01242", "type": "abstain"}
```

- Những câu hỏi bị thiếu trong file `submission.jsonl` sẽ được chấm là `abstain`.
- Trường `"reason"` (lý do) là tùy chọn (*optional*).
- Số lần được phép nộp bài mỗi ngày tuân theo quy chế chung của cuộc thi.

### 5.2. Đóng gói Docker Image (`Docker image`)
- **Docker image** (xem mục *Competition rounds* trong file `rule.md`) bắt buộc phải chứa:
  1. Toàn bộ mã nguồn (*source code*: cả *training* và *inference*).
  2. Trọng số mô hình (*model weights*).
  3. File kịch bản thực thi **`predict.sh`** có nhiệm vụ đọc tập kiểm tra từ `/data` và ghi kết quả ra `/result/submission.jsonl`.
  4. Một file `README` thuyết minh giải pháp.
- **Ghi nhật ký từng câu hỏi (`/result/logs/`):**
  Image cũng phải ghi lại log cho từng câu hỏi vào thư mục `/result/logs/` (bất kỳ định dạng nào), chứa tối thiểu:
  - Mã câu hỏi (`question id`)
  - Câu trả lời cuối cùng (`final answer`)
  - Thời gian xử lý câu hỏi đó (`elapsed time`)
  - Cùng các thông tin minh chứng cách tìm ra câu trả lời (ví dụ: đoạn code được sinh ra — *generated code*, kết quả chạy code — *execution output*).
  Ban Tổ chức sẽ sử dụng các file log này để đối chiếu và giải quyết nếu có sự chênh lệch điểm số giữa kết quả bạn tải lên và lần chạy lại (*re-run*) của Ban Tổ chức (Quy định 8).
