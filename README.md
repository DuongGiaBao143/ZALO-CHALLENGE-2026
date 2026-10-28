# Zalo AI Challenge 2026 — DataMate (Team Repository)

Repository chính thức của đội thi cho bài toán **DataMate: Natural-Language Vietnamese Question Answering over Tabular Data** tại **Zalo AI Challenge 2026**.

---

## 📚 Tài liệu cuộc thi (Đã dịch sang tiếng Việt)

Tất cả thành viên trong team **bắt buộc đọc kỹ 4 file tài liệu dưới đây** trước khi code:
1. 📄 [Mô tả bài toán (`description.md`)](./description.md): Tổng quan bài toán, định dạng Input/Output.
2. 📊 [Cách thức chấm điểm (`evaluation.md`)](./evaluation.md): Công thức **Penalized Accuracy ($\text{PA}$)** ($+1 / 0 / -1$), quy tắc chuẩn hóa `string` (`Unicode NFC`), quy tắc `list`/`table`/`ranking`.
3. ⚖️ [Thể lệ & Yêu cầu kỹ thuật (`rule.md`)](./rule.md): Giới hạn tổng tham số $\le 15\text{B}$, chạy hoàn toàn offline trong Docker trên `2 × NVIDIA RTX 5090 (64GB VRAM)`, `CUDA ≥ 12.8`, điều kiện tái lập kết quả $|\text{PA}_{\text{uploaded}} - \text{PA}_{\text{re-run}}| \le 0.03$.
4. 🚀 [Hướng dẫn & Lịch trình nộp bài (`submission_guidance.md`)](./submission_guidance.md): Các mốc thời gian Vòng Public Test (`26/10 – 16/11`) và Vòng Private Test (`20/11 – 23/11`).

---

## 🏗️ Kiến trúc hệ thống (System Architecture)

```text
questions.jsonl + /data/<business_id> (.csv, .xlsx, .sqlite, README.md)
       │
       ▼
┌───────────────────────────────────────────────────────────────────┐
│ 1. Data Profiler (`src/profiler/business_loader.py`)              │
│    Trích xuất tự động tên bảng, tên cột, kiểu dữ liệu, dòng mẫu   │
│    và các giá trị phân loại (categorical values) của doanh nghiệp │
└───────────────────────────────────────────────────────────────────┘
       │
       ▼
┌───────────────────────────────────────────────────────────────────┐
│ 2. Time & Rulebook Resolver (`src/time_resolver/calendar_utils.py`)│
│    Quy đổi sẵn `as_of_date` ("tuần rồi", "tháng này", "năm ngoái")│
│    bằng Python + nạp `rulebook` và lịch Âm - Dương dùng chung      │
└───────────────────────────────────────────────────────────────────┘
       │
       ▼
┌───────────────────────────────────────────────────────────────────┐
│ 3. Code-Execution Agent (`src/agent/solver.py` + `sandbox.py`)    │
│    LLM (<= 15B tham số, chạy qua vLLM) sinh code Python/Pandas/SQL│
│    chạy trong Sandbox chỉ đọc (`/data`), tự sửa lỗi nếu crash     │
└───────────────────────────────────────────────────────────────────┘
       │
       ▼
┌───────────────────────────────────────────────────────────────────┐
│ 4. Normalizer & Abstain Gate (`src/postprocess/normalizer.py`)    │
│    Chuẩn hóa kết quả đúng chuẩn Evaluation (NFC, làm tròn 2 số).  │
│    Nếu không chắc chắn -> trả về `abstain` (0 điểm) để tránh -1!  │
└───────────────────────────────────────────────────────────────────┘
       │
       ▼
/result/submission.jsonl
```

---

## 📁 Cấu trúc thư mục (Repository Structure)

```text
.
├── configs/
│   └── default_config.yaml         # Cấu hình model (<=15B), vLLM, seed cố định, đường dẫn
├── data/                           # (Ignored bởi Git) Đặt dữ liệu cuộc thi tại đây
│   └── README.md                   # Hướng dẫn đặt dữ liệu cho các thành viên
├── result/                         # Thư mục xuất file submission.jsonl và run.log
├── scripts/
│   ├── run_inference.py            # Script chính chạy từ /data -> /result/submission.jsonl
│   ├── evaluate_local.py           # Script chấm điểm Penalized Accuracy (PA) nội bộ
│   └── verify_submission.py        # Kiểm tra định dạng submission.jsonl & in mã SHA256
├── src/
│   ├── schemas.py                  # Định nghĩa kiểu dữ liệu đầu vào/đầu ra
│   ├── profiler/                   # Module 1: Đọc và trích xuất schema (.csv, .xlsx, .sqlite)
│   ├── time_resolver/              # Module 2: Xử lý thời gian tương đối & lịch Âm-Dương
│   ├── agent/                      # Module 3: Prompting, vLLM inference & Sandbox chạy code
│   ├── postprocess/                # Module 4: Chuẩn hóa câu trả lời & Abstain Gate
│   └── eval/                       # Bộ chấm điểm PA khớp 100% với evaluation.md
├── tests/
│   └── test_eval_and_normalizer.py # Unit tests kiểm tra bộ chấm điểm và chuẩn hóa
├── Dockerfile                      # Đóng gói chuẩn CUDA 12.8 cho 2x RTX 5090 (offline)
├── requirements.txt                # Các thư viện Python cần thiết
├── description.md
├── evaluation.md
├── rule.md
└── submission_guidance.md
```

---

## 🛠️ Hướng dẫn cài đặt & Sử dụng cho Team

### 1. Cài đặt môi trường cục bộ (Local Development)

```bash
python -m venv .venv
# Trên Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Trên Linux / macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Chạy Unit Tests kiểm tra hệ thống chấm điểm & chuẩn hóa

```bash
pytest -v
```

### 3. Chạy thử nghiệm Pipeline (Dry-run không cần GPU)

```bash
python scripts/run_inference.py \
  --config configs/default_config.yaml \
  --data-dir data \
  --output result/submission.jsonl \
  --dry-run
```

### 4. Chấm điểm cục bộ trên tập Train / Validation (`Penalized Accuracy`)

```bash
python scripts/evaluate_local.py \
  --pred result/submission.jsonl \
  --gold data/train_answers.jsonl
```

### 5. Kiểm tra file `submission.jsonl` trước khi nộp lên cổng Zalo AI

```bash
python scripts/verify_submission.py \
  --submission result/submission.jsonl \
  --questions data/questions.jsonl
```

---

## 🐳 Đóng gói và chạy Docker Offline (Tuân thủ Rule 3, 5, 7, 8)

```bash
# 1. Build Docker image
docker build -t datamate-solution:latest .

# 2. Chạy kiểm thử giống hệt môi trường chấm của Ban Tổ chức:
#    - Vô hiệu hóa mạng (--network none)
#    - Mount /data ở chế độ chỉ đọc (:ro)
#    - Thu thập kết quả tại /result/submission.jsonl
docker run --rm --gpus all --network none \
  -v $(pwd)/data:/data:ro \
  -v $(pwd)/result:/result \
  datamate-solution:latest
```

---

## 📋 Bảng kê khai mô hình (Model Declaration — Rule 2)

| Vai trò | Tên mô hình (Hugging Face) | Số tham số | Ngày phát hành | Ghi chú |
| :--- | :--- | :---: | :---: | :--- |
| Code Generation & QA Agent | `Qwen/Qwen2.5-Coder-14B-Instruct` | `14.7B` ($\le 15\text{B}$) | Trước `01/10/2026` | Chạy offline qua `vLLM` (`temperature=0.0`, `seed=42`) |
