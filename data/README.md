# Thư mục Dữ liệu (`data/`)

> **Lưu ý:** Toàn bộ dữ liệu thô trong thư mục này đã được đưa vào `.gitignore` để tránh đẩy các file dung lượng lớn lên GitHub.

Mỗi thành viên trong team sau khi tải bộ dữ liệu từ cổng thông tin **Zalo AI Challenge 2026** hãy giải nén vào thư mục `data/` theo cấu trúc:

```text
data/
├── rulebook.md                # Bộ quy tắc dùng chung
├── calendar.csv               # Lịch Âm - Dương dùng chung
├── questions.jsonl            # Danh sách câu hỏi của split hiện tại
└── businesses/                # (hoặc đặt trực tiếp các thư mục biz_xxx/ tại data/)
    ├── biz_001/
    │   ├── README.md
    │   ├── orders.csv
    │   ├── products.xlsx
    │   └── inventory.sqlite
    └── biz_118/
        └── ...
```
