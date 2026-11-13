# DataMate — Zalo AI Challenge 2026

> 🏆 **Dự án thi đấu Zalo AI Challenge 2026 — Track: DataMate (Natural-Language Vietnamese Question Answering over Tabular Data)**  
> 🤖 **Tài liệu hướng dẫn dành cho Developer & AI Coding Agent (Cursor, Claude Code, Copilot, Antigravity...) tiếp nhận dự án.**

---

## 📌 ĐỌC ĐẦU TIÊN KHI TIẾP NHẬN REPO (QUICK ONBOARDING)

Nếu bạn là **Developer** hoặc **AI Agent** vừa kéo repository này về, hãy nắm ngay 3 điểm cốt lõi:

1. **Tài liệu quy hoạch kỹ thuật chi tiết nhất:** Mở và đọc ngay file **[`HANDOFF_PLAN.md`](HANDOFF_PLAN.md)** (1.191 dòng) ở thư mục gốc. Tài liệu này chứa toàn bộ đặc tả hàm, mã nguồn mẫu, cơ chế ReAct Ephemeral Thinking, phân tích pháp y các ca sai trên 30 câu Dev, và hướng dẫn thực thi 4 task kỹ thuật.
2. **Quy tắc bất khả xâm phạm:** Xem **[`AGENTS.md`](AGENTS.md)**. Thư mục `data/` là **RAW DATA CHỈ ĐỌC 100% (STRICTLY READ-ONLY)**. Mọi thao tác ghi đè, đổi tên, hoặc sửa file trong `data/` đều bị nghiêm cấm tuyệt đối.
3. **Mô hình mục tiêu (Baseline):** Dự án sử dụng **`Qwen/Qwen2.5-14B-Instruct-1M`** (14.7B tham số $\le 15\text{B}$, tuân thủ 100% Rule 2 của cuộc thi, chạy hoàn toàn offline trong container Docker 64GB VRAM).

---

## ⚖️ ĐIỀU LỆ THI ĐẤU & CÔNG THỨC CHẤM ĐIỂM (PENALIZED ACCURACY)

Điểm số xếp hạng được tính theo công thức **Penalized Accuracy (PA)**:

$$\text{PA} = \frac{1}{N} \sum_{i=1}^{N} S(y_i, \hat{y}_i)$$

Trong đó:
* **$+1.0$ điểm:** Trả lời **ĐÚNG** đáp án.
* **$0.0$ điểm:** Trả về **`"abstain"`** (chủ động từ chối khi thiếu dữ kiện hoặc không đủ độ tin cậy).
* **$-1.0$ điểm:** Trả lời **SAI** (bị phạt nặng vì ảo giác / đoán mò!).

> [!IMPORTANT]
> ### NGUYÊN TẮC CHIẾN LƯỢC: "THÀ TỪ CHỐI CÒN HƠN ĐOÁN MÒ"
> Vì mỗi câu sai bị phạt **$-1.0$ điểm** (triệt tiêu 1 câu đúng), mục tiêu tối thượng của Agent là:
> - Chỉ chốt đáp án khi đã thăm dò dữ liệu (`observation`) và có căn cứ xác thực (`check.rows_after_filter > 0`).
> - Khi gặp bẫy lọc rỗng, câu hỏi ngoài phạm vi ngày (Rulebook §7), hoặc câu hỏi thiếu cột thông tin $\rightarrow$ **ép trả về `"abstain"` ngay để lấy 0.0 điểm an toàn**.

---

## 🏛️ KIẾN TRÚC AGENT: LEAN BOUNDED REACT

Hệ thống hoạt động theo mô hình **ReAct (Reasoning + Acting) tinh gọn 2–3 turns**:

```
                              [CÂU HỎI TIẾNG VIỆT + AS_OF_DATE]
                                              │
                                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  TURN 1: KHÁM PHÁ & XÁC MINH DỮ LIỆU (DISCOVERY)                                       │
│  - Mô hình sinh 3-5 dòng Thought (phân tích metric, check luật ngành trong Rulebook)   │
│  - Gọi Lean Helpers kiểm tra nhãn: explore_data(), fuzzy_find()                        │
│  - Trả về kind="observation" (cắt gọn <= 4000 ký tự)                                   │
└─────────────────────────────────────────────┬──────────────────────────────────────────┘
                                              │
                                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  CƠ CHẾ EPHEMERAL THINKING (TIẾT KIỆM CỬA SỔ NGỮ CẢNH 16.384 TOKENS)                   │
│  - Bóc tách toàn bộ khối <think> thô của Turn 1 trước khi gửi vào lịch sử Turn 2        │
│  - Chỉ giữ lại: Tóm tắt kế hoạch 3 dòng + Mã Python + Kết quả Observation              │
└─────────────────────────────────────────────┬──────────────────────────────────────────┘
                                              │
                                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  TURN 2: TÍNH TOÁN & CHỐT ĐÁP ÁN (FINAL CANDIDATE)                                     │
│  - Nạp dữ liệu sạch chuẩn Rulebook §8: load_clean_df(), resolve_date()                  │
│  - Tính toán và phát tín hiệu: emit_final(answer, type, evidence, check={...})         │
└─────────────────────────────────────────────┬──────────────────────────────────────────┘
                                              │
                                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  CỔNG KIỂM DUYỆT ABSTAIN-FIRST GATE (_eval_guard_issue trong solver.py)                 │
│  - Chặn bẫy lọc rỗng (rows_after_filter == 0)                                          │
│  - Chặn câu hỏi ngoài vùng ngày dữ liệu (Rulebook §7)                                  │
│  - Chặn kết quả 0 / danh sách [0, 0] / bảng nợ toàn 0 chưa kiểm chứng                  │
│  ==> Nếu vi phạm hoặc không chắc chắn: TỰ ĐỘNG ÉP VỀ "abstain" (0.0 điểm an toàn)      │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🧰 BỘ 6 CÔNG CỤ TINH GỌN (DOMAIN-AGNOSTIC LEAN HELPERS)

Toàn bộ công cụ trong Sandbox (`src/agent/sandbox.py`) được thiết kế **hoàn toàn phi ngành nghề (domain-agnostic)** để thích ứng tự động với mọi ngành nghề mới trong Private Test:

| Tên Helper | Mục Đích Kỹ Thuật | Đầu Ra Trả Về |
|---|---|---|
| `explore_data(file, column=None, keyword=None, n=5)` | Khám phá nhanh cấu trúc, kiểu dữ liệu, khoảng ngày `[min_date, max_date]`, và đếm giá trị độc nhất. | `dict` thống kê schema & dữ liệu |
| `fuzzy_find(df_or_file, column, query, top_k=5, cutoff=0.5)` | Tìm kiếm mờ tiếng Việt xóa dấu (`vn_norm`) cho tên sản phẩm, khách hàng viết tắt hoặc sai chính tả. | `list[tuple(giá trị, điểm độ khớp)]` |
| `load_clean_df(file, sheet=0, dedup_order=True, as_of_date=None)` | Tự động unmerge, dò header, khử trùng lặp dòng nội bộ cùng đơn hàng (Rulebook §8), và lọc theo `as_of_date`. | `pd.DataFrame` đã chuẩn hóa sạch |
| `resolve_date(expr, as_of_date=None)` | Phân giải biểu thức thời gian tương đối (Rulebook §2) kết hợp tra cứu lịch âm/Tết từ `calendar.csv`. | `dict(start_date, end_date, ...)` |
| `emit_obs(data, msg)` | Xuất kết quả quan sát chuẩn giao thức BTC giữa các turn, tự động làm sạch NaN và giới hạn độ dài. | Protocol JSON `kind="observation"` |
| `emit_final(answer, type, evidence, check=None, reason=None)` | Xuất đáp án cuối cùng kèm sanity check (kiểu dữ liệu, làm tròn, Unicode NFC) chuẩn quy cách nộp bài. | Protocol JSON `kind="final"` |

---

## 🗺️ BẢN ĐỒ CẤU TRÚC CODEBASE

```text
.
├── HANDOFF_PLAN.md                  # TÀI LIỆU QUY HOẠCH CHI TIẾT 1.191 DÒNG (ĐỌC KỸ TRƯỚC KHI CODE)
├── AGENTS.md                        # QUY TẮC BẤT KHẢ XÂM PHẠM CHO AI AGENT & DEVELOPER
├── README.md                        # File này (Tổng quan dự án & Hướng dẫn onboarding)
├── Dockerfile                       # Cấu hình container thi đấu offline CUDA 12.8
├── predict.sh                       # Entrypoint chạy suy luận theo thể lệ của BTC
├── requirements.txt                 # Thư viện phụ thuộc Python cơ sở
├── configs/                         # File cấu hình tham số hệ thống & vLLM
│   └── default_config.yaml          # Cấu hình mặc định của agent và model
├── docs/                            # Tài liệu thể lệ và dữ liệu chính thức từ BTC
│   ├── rule.md                      # Toàn văn quy chế thi đấu
│   ├── evaluation.md                # Quy tắc tính điểm Penalized Accuracy & kiểu dữ liệu
│   ├── description.md               # Mô tả chi tiết bài toán
│   └── data.md                      # Cấu trúc gói dữ liệu doanh nghiệp
├── data/                            # [STRICTLY READ-ONLY] Dữ liệu thô từ BTC (30 shop train + 14 shop public test)
├── notebooks/                       # Google Colab & Kaggle notebooks
│   └── Evaluate_Qwen25_14B_1M_Colab_G4.ipynb  # Notebook đánh giá chính thức trên Colab (A100-40GB)
├── src/                             # MÃ NGUỒN CỐT LÕI CỦA AGENT
│   ├── agent/
│   │   ├── sandbox.py               # Môi trường thực thi Python độc lập + Nơi chứa 6 Lean Helpers
│   │   ├── solver.py                # Vòng lặp Agent ReAct, Ephemeral Thinking & Abstain Gate
│   │   └── prompts.py               # Prompt templates & nạp Rulebook động
│   ├── profiler/
│   │   └── business_loader.py       # Trích xuất schema CSV/XLSX/SQLite + format nhãn phân loại
│   ├── time_resolver/
│   │   └── calendar_utils.py        # Xử lý thời gian tương đối & tra cứu lịch âm calendar.csv
│   ├── postprocess/
│   │   ├── normalizer.py            # Chuẩn hóa đáp án đầu ra (Unicode NFC, làm tròn 2 số thập phân)
│   │   └── vn_utils.py              # Xử lý tiếng Việt (xóa dấu vn_norm, parse số, parse ngày)
│   ├── eval/
│   │   ├── metric.py                # Công thức tính điểm PA chuẩn xác
│   │   └── scorer.py                # Bộ chấm điểm local đối chiếu với gold
│   └── schemas.py                   # Data classes & định nghĩa giao thức JSON
├── scripts/                         # Các kịch bản chạy suy luận và đóng gói
│   ├── evaluate_pilot_30.py         # Script chấm điểm 30 câu Dev benchmark
│   └── package_and_upload_bundle.py # Đóng gói mã nguồn & đẩy bundle lên HuggingFace
└── tests/                           # Bộ kiểm thử Unit test (đang pass 100%)
```

---

## 🚀 HƯỚNG DẪN BẮT ĐẦU NHANH (QUICK START)

### 1. Cài đặt môi trường cục bộ
```bash
# Khởi tạo môi trường ảo Python 3.10+
python -m venv .venv
source .venv/bin/activate  # Trên Linux/macOS
# hoặc .venv\Scripts\activate trên Windows

# Cài đặt dependencies
pip install -r requirements.txt
```

### 2. Chạy bộ kiểm thử tự động
```bash
# Chạy toàn bộ unit tests (bắt buộc pass 100% trước khi commit)
python -m pytest tests/ -v
```

### 3. Đánh giá trên Google Colab (A100-40GB)
Mở notebook [`notebooks/Evaluate_Qwen25_14B_1M_Colab_G4.ipynb`](notebooks/Evaluate_Qwen25_14B_1M_Colab_G4.ipynb):
1. Notebook tự động tải bundle mã nguồn mới nhất từ HuggingFace repo `Crinkk/Zalo-challenge`.
2. Tải trọng số `Qwen/Qwen2.5-14B-Instruct-1M`.
3. Chạy đánh giá đối đầu (Base vs Base+LoRA) trên 30 câu hỏi Dev unseen.
4. Tự động tính điểm PA và xuất kết quả đối chứng `comparison.json`.

---

## 📋 4 GÓI NHIỆM VỤ CẦN TRIỂN KHAI (IMPLEMENTATION TASKS)

Theo kế hoạch bàn giao chi tiết tại **Mục 6 trong [`HANDOFF_PLAN.md`](HANDOFF_PLAN.md)**, người nhận bàn giao cần tiến hành 4 task sau:

* [ ] **Task 1: Cài đặt 6 Lean Helpers vào `src/agent/sandbox.py`**
  - Hiện thực hóa 6 hàm: `explore_data`, `fuzzy_find`, `load_clean_df`, `resolve_date`, `emit_obs`, `emit_final`.
  - Viết unit test độc lập kiểm thử cả 6 hàm trong `tests/`.
* [ ] **Task 2: Cài đặt Ephemeral Thinking & Thích ứng Luật Động vào `src/agent/solver.py`**
  - Cài đặt hàm `prune_ephemeral_thinking()` để bóc tách `<think>` cũ ở Turn $\ge 2$, bảo vệ context window 16.384 tokens.
  - Cập nhật `src/agent/prompts.py` nạp động `rulebook.md` runtime và `README.md` của từng shop; ép model viết `Thought:` 3–5 dòng trước khi xuất code.
* [ ] **Task 3: Nâng cấp Abstain-First Gate trong `src/agent/solver.py`**
  - Bổ sung các luật chặn trong `_eval_guard_issue`: bẫy lọc rỗng (`rows_after_filter == 0`), câu hỏi ngoài vùng ngày dữ liệu, và kết quả 0 chưa kiểm chứng.
  - Tự động fallback sang `"abstain"` (nhận 0.0 điểm an toàn) khi gặp lỗi hoặc không chắc chắn.
* [ ] **Task 4: Chạy Benchmark Colab & Chuẩn hóa Dataset SFT ReAct**
  - Chạy notebook `Evaluate_Qwen25_14B_1M_Colab_G4.ipynb` trên 30 câu Dev, xác thực điểm $\text{PA} \ge +0.4000$.
  - Xây dựng dataset SFT định dạng ReAct đa lượt (`sft_react_trajectories.jsonl`) để fine-tune LoRA mới (tuyệt đối không dùng lại dataset SFT code-only cũ).

---

## 🔒 CAM KẾT AN TOÀN DỮ LIỆU & QUY ĐỊNH DOCKER
1. **Dữ liệu thô `data/`:** Tuyệt đối không ghi đè, đổi tên, hoặc tạo file rác trong thư mục `data/`.
2. **Môi trường thi đấu:** Container chạy offline hoàn toàn (`--network none`), mount thư mục `/data:ro`.
3. **Tính tất định:** Luôn cố định `seed=42`, `temperature=0.0` để sai số điểm số $|\text{PA}_{\text{uploaded}} - \text{PA}_{\text{re-run}}| \le 0.03$.
