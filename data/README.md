# Thư mục Dữ liệu (`data/`)

Dữ liệu của cuộc thi đã được giải nén sẵn vào hai thư mục `data/train/` và `data/public_test/` để toàn bộ thành viên trong team có thể sử dụng ngay sau khi `git pull` (hai file nén gốc `.zip` đã được chặn trong `.gitignore` vì vượt giới hạn 100 MB/file của GitHub).

```text
data/
├── train/                           # Tập Training (30 doanh nghiệp, 3.000 câu hỏi + đáp án)
│   ├── data/
│   │   ├── biz_101/                 # (*.csv, *.xlsx, *.sqlite + README.md)
│   │   └── ... (biz_101 -> biz_130)
│   ├── rulebook.md                  # Bộ quy tắc của tập train
│   ├── calendar.csv                 # Lịch Dương - Âm (2024 - 2027)
│   ├── questions.jsonl              # 3.000 câu hỏi
│   └── answers.jsonl                # 3.000 đáp án chuẩn (kèm trường alias)
│
└── public_test/                     # Tập Public Test (14 doanh nghiệp, 1.000 câu hỏi)
    ├── data/
    │   ├── dev_001/
    │   └── ... (dev_001 -> dev_014)
    ├── rulebook.md                  # Bộ quy tắc của tập public_test (có thêm ngành mới!)
    ├── calendar.csv                 # Lịch Dương - Âm
    └── questions.jsonl              # 1.000 câu hỏi kiểm tra công khai
```
