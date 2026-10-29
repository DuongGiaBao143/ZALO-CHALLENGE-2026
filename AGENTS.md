# AGENT GUIDELINES — Zalo AI Challenge 2026: DataMate

> ⚠️ **TÀI LIỆU DÀNH CHO TẤT CẢ CÁC AI AGENT & DEVELOPER LÀM VIỆC TRONG DỰ ÁN NÀY**  
> Mọi AI Agent (Antigravity, Cursor, Copilot, Claude Code...) khi tham gia đọc, phân tích hoặc sinh mã nguồn trong repository này **BẮT BUỘC** phải tuân thủ nghiêm ngặt các quy tắc dưới đây.

---

## ⛔ ĐIỀU RĂN TỐI CAO: TUYỆT ĐỐI BẢO TOÀN DỮ LIỆU THÔ (RAW DATA)

> [!CAUTION]
> ### NGUYÊN TẮC BẤT KHẢ XÂM PHẠM VỀ THƯ MỤC `data/`
> 1. **DỮ LIỆU THÔ 100% NGUYÊN BẢN:**  
>    Toàn bộ dữ liệu nằm trong thư mục `data/` (bao gồm `data/train/`, `data/public_test/`, các thư mục con `biz_xxx/`, `dev_xxx/`, file `calendar.csv`, `rulebook.md`, `questions.jsonl`, `answers.jsonl`, và mọi file `.csv`, `.xlsx`, `.sqlite`, `.md`) **LÀ RAW DATA DO BAN TỔ CHỨC CUNG CẤP**.
> 2. **CHẾ ĐỘ CHỈ ĐỌC (STRICTLY READ-ONLY):**  
>    - **TUYỆT ĐỐI KHÔNG** sửa đổi, đổi tên, ghi đè, định dạng lại (reformat), hoặc xóa bất kỳ file/thư mục nào trong `data/`.
>    - **TUYỆT ĐỐI KHÔNG** chạy các script tiền xử lý ghi đè trực tiếp lên file gốc trong `data/`.
>    - **TUYỆT ĐỐI KHÔNG** tự ý "dọn dẹp" các file `README.md` hay `rulebook.md` nằm trong `data/` — đó là tài liệu ngữ cảnh nghiệp vụ mà mô hình AI bắt buộc phải đọc.
> 3. **XỬ LÝ DỮ LIỆU TẠM THỜI:**  
>    Nếu cần tạo dữ liệu trung gian, cache, index, hoặc xuất file tạm, **PHẢI** lưu vào thư mục `tmp/`, `result/`, hoặc xử lý hoàn toàn trong bộ nhớ RAM (`in-memory`). Không bao giờ ghi vào `data/`.
> 4. **MÔI TRƯỜNG DOCKER CHÍNH THỨC:**  
>    Khi chấm điểm, BTC sẽ gắn (`mount`) thư mục dữ liệu ở chế độ chỉ đọc: `/data:ro`. Mọi hành động cố tình ghi vào thư mục data sẽ làm sập container và bị loại ngay lập tức.

---

## 1. TỔNG QUAN BÀI TOÁN & ĐỀ TÀI (OVERVIEW)

### 1.1. Tên bài toán & Mục tiêu
* **Cuộc thi:** Zalo AI Challenge 2026.
* **Đề tài:** **DataMate — Natural-Language Vietnamese Question Answering over Tabular Data** (Hỏi đáp bằng ngôn ngữ tự nhiên Tiếng Việt trên dữ liệu bảng biểu doanh nghiệp).
* **Bối cảnh thực tế:** Các hộ kinh doanh, tiệm tạp hóa, quán cà phê, nhà thuốc... tại Việt Nam lưu trữ dữ liệu bán hàng, kho, sổ nợ bằng Excel (`.xlsx`), CSV, hoặc SQLite. Dữ liệu thực tế rất lộn xộn (*messy*), thiếu nhất quán, và không theo một chuẩn duy nhất.
* **Mục tiêu của Agent:** Xây dựng một AI Agent có khả năng đọc các file dữ liệu thô của doanh nghiệp cùng câu hỏi bằng Tiếng Việt đời thường, tự động phân tích/truy vấn để đưa ra câu trả lời chính xác — hoặc **từ chối trả lời (`abstain`)** nếu dữ liệu không đủ căn cứ.

### 1.2. Định dạng Đầu vào (Input)
Khi chạy suy luận cho một câu hỏi, Agent nhận:
1. **Gói dữ liệu doanh nghiệp (`business_id`):** Một hoặc nhiều file `.csv`, `.xlsx`, `.sqlite` kèm một file `README.md` ngắn mô tả quy ước kinh doanh riêng của quán/doanh nghiệp đó.
2. **File quy tắc chung (`rulebook.md`):** Quy định các quy ước tính toán nghiệp vụ (chiết khấu, công nợ, ca làm việc...).
3. **Câu hỏi (`question`):** Câu hỏi bằng Tiếng Việt tự nhiên (ví dụ: *"Tháng này bán chạy nhất mặt hàng gì?"*, *"Hôm qua có bao nhiêu khách nợ tiền?"*).
4. **Ngày mốc tham chiếu (`as_of_date`):** Ngày đóng vai trò là "hôm nay", dùng để phân giải các mốc thời gian tương đối (*"hôm nay"*, *"tuần trước"*, *"tháng này"*, *"cùng kỳ năm ngoái"*).

### 1.3. Định dạng Đầu ra (Output)
Agent phải xuất kết quả ra file `result/submission.jsonl` với cấu trúc từng dòng:
```json
{"question_id": "dev_001_q001", "answer": ...}
```
Các kiểu dữ liệu hợp lệ của `answer`:
* **Số (`number`):** Làm tròn tối đa 2 chữ số thập phân (`round(val, 2)`).
* **Chuỗi (`string`):** Chuẩn hóa Unicode NFC, xóa khoảng trắng thừa, giữ nguyên dấu tiếng Việt.
* **Danh sách (`list`):** Danh sách các giá trị tương ứng.
* **Bảng / Xếp hạng (`table` / `ranking`):** Cấu trúc bảng theo quy định của đề bài.
* **Từ chối trả lời (`"abstain"`):** Trả về chuỗi `"abstain"` khi câu hỏi không thể trả lời được từ dữ liệu.

---

## 2. CÁC QUY TẮC & THỂ LỆ CUỘC THI (COMPETITION RULES)

### Rule 1: Môi trường Chạy & Đóng gói Docker Offline
* Toàn bộ giải pháp nộp bài phải đóng gói dưới dạng **Docker Image**.
* Container chạy **hoàn toàn offline (`--network none`)**, không được kết nối Internet để gọi API bên ngoài.
* Điểm kích hoạt chương trình là script `predict.sh` nằm ở thư mục gốc repo.

### Rule 2: Giới hạn Mô hình (Model Constraints)
* **Tổng số tham số của tất cả các mô hình $\le 15\text{B}$** (ví dụ: Qwen2.5-Coder-14B, v.v.).
* Chỉ được dùng các mô hình nguồn mở (open-weights) đã công bố trước ngày `01/10/2026`.
* Toàn bộ trọng số (weights) phải được tải sẵn và đóng gói bên trong Docker image.

### Rule 3: Cấu hình Phần cứng Thẩm định
* Ban Tổ Chức thẩm định giải pháp trên máy chủ:
  * **GPU:** `2 × NVIDIA RTX 5090 (64GB VRAM tổng cộng)`.
  * **Driver / CUDA:** `CUDA ≥ 12.8`.
* Giải pháp phải tự tối ưu hóa VRAM (sử dụng vLLM, TensorRT-LLM hoặc llama.cpp) để chạy ổn định mà không bị lỗi Out-Of-Memory (OOM).

### Rule 4: Ghi Log bắt buộc (Logging Requirement)
* Song song với file `submission.jsonl`, hệ thống bắt buộc phải ghi log chi tiết quá trình suy luận của từng câu hỏi vào:
  ```text
  /result/logs/<question_id>.json
  ```
* Log bao gồm: Prompt, mã code sinh ra, kết quả thực thi code, và thời gian xử lý.

### Rule 5: Độ Ổn định & Tái lập Kết quả (Reproducibility)
* Sai số điểm số giữa kết quả nộp trên Public Leaderboard và kết quả khi BTC chạy lại container không được lệch quá $0.03$:
  $$\left|\text{PA}_{\text{uploaded}} - \text{PA}_{\text{re-run}}\right| \le 0.03$$
* Bắt buộc phải cố định `seed` ngẫu nhiên (ví dụ `seed=42`) và đặt `temperature=0.0` trong LLM để đảm bảo tính tất định.

---

## 3. CÔNG THỨC CHẤM ĐIỂM — PENALIZED ACCURACY (PA)

Điểm số của cuộc thi được tính bằng công thức **Penalized Accuracy**:

$$\text{PA} = \frac{1}{N} \sum_{i=1}^{N} S(y_i, \hat{y}_i)$$

Trong đó, điểm $S(y_i, \hat{y}_i)$ cho mỗi câu hỏi:
* **$+1.0$ điểm:** Trả lời **ĐÚNG** đáp án.
* **$0.0$ điểm:** Trả về **`abstain`** (từ chối trả lời).
* **$-1.0$ điểm:** Trả lời **SAI** (bị phạt nặng vì ảo giác / hallucination!).

> [!IMPORTANT]
> ### CHIẾN LƯỢC CỦA AGENT: "THÀ TỪ CHỐI CÒN HƠN ĐOÁN MÒ"
> Vì điểm sai bị trừ tới **$-1.0$ điểm** (thay vì $0$ như các cuộc thi thông thường), nếu Agent cảm thấy độ tự tin thấp, câu hỏi thiếu dữ kiện, hoặc code thực thi bị lỗi không ra kết quả -> **BẮT BUỘC PHẢI TRẢ VỀ `"abstain"` ĐỂ LẤY 0 ĐIỂM, TUYỆT ĐỐI KHÔNG ĐƯỢC ĐOÁN BỪA**.

---

## 4. BẢN ĐỒ CẤU TRÚC REPOSITORY (CODEBASE MAP)

```text
.
├── agent.md                        # File này (Kim chỉ nam cho AI Agent)
├── README.md                       # Tài liệu tổng quan repository của team
├── Dockerfile                      # Cấu hình container chạy offline CUDA 12.8
├── predict.sh                      # Entrypoint chạy theo yêu cầu của BTC
├── requirements.txt                # Thư viện phụ thuộc (Python 3.10+)
├── configs/                        # Cấu hình hệ thống & tham số vLLM/Model
├── docs/                           # Tài liệu gốc chi tiết của cuộc thi
│   ├── description.md              # Mô tả chi tiết bài toán
│   ├── data.md                     # Cấu trúc gói dữ liệu & submission
│   ├── evaluation.md               # Chi tiết công thức PA & quy tắc chuẩn hóa
│   ├── rule.md                     # Toàn văn thể lệ thi đấu
│   └── submission_guidance.md      # Mốc thời gian & hướng dẫn nộp Docker
├── data/                           # [NGHIÊM CẤM CHỈNH SỬA] Raw data của BTC
│   ├── train/                      # 30 shop mẫu + answers.jsonl
│   └── public_test/                # 14 shop test + questions.jsonl
├── result/                         # Nơi chứa kết quả chạy (submission.jsonl + logs/)
├── scripts/                        # Các kịch bản chạy suy luận và đánh giá nội bộ
│   ├── run_inference.py            # Chạy toàn bộ pipeline
│   ├── evaluate_local.py           # Chấm điểm PA nội bộ
│   └── verify_submission.py        # Kiểm tra tính hợp lệ trước khi nộp
├── src/                            # Mã nguồn kiến trúc Agent cốt lõi
│   ├── profiler/                   # Trích xuất cấu trúc dữ liệu (.csv, .xlsx, .sqlite)
│   ├── time_resolver/              # Xử lý thời gian tương đối & lịch âm dương
│   ├── agent/                      # Solver, Sandbox sinh và chạy code
│   ├── postprocess/                # Chuẩn hóa Unicode NFC, định dạng kết quả
│   └── eval/                       # Bộ tính điểm PA chuẩn xác theo BTC
└── tests/                          # Bộ kiểm thử Unit test
```

---

## 5. TỔNG KẾT HÀNH ĐỘNG CHO AGENT
Khi làm việc trên codebase này:
1. **Trước khi lập trình tính năng mới:** Đọc kỹ tài liệu liên quan trong `docs/`.
2. **Khi tương tác với dữ liệu:** Luôn mở file với chế độ chỉ đọc (`read-only`, `r`, `sqlite3.connect(..., uri=True)` với `?mode=ro`).
3. **Khi xử lý câu trả lời:** Luôn đi qua bộ lọc `normalizer` và cổng tự kiểm duyệt độ tin cậy (`Abstain Gate`).
