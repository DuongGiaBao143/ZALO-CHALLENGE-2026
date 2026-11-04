# TÀI LIỆU BÀN GIAO HUẤN LUYỆN MODEL (HANDOFF: SFT QWEN-7B KAGGLE 2×T4)

> **Dự án:** Zalo AI Challenge 2026 — DataMate  
> **Nhiệm vụ:** Huấn luyện SFT mô hình Qwen2.5-Coder-7B-Instruct trên 890 mẫu đã kiểm định bằng LoRA FP16 + FSDP trên 2× GPU NVIDIA T4 (Kaggle).  
> **Người tiếp nhận:** Kỹ sư Huấn luyện Mô hình (ML/Training Engineer)  
> **File Notebook chính:** [`notebooks/02_train_sft_qwen7b_kaggle_2t4_890.ipynb`](../notebooks/02_train_sft_qwen7b_kaggle_2t4_890.ipynb)

---

## 1. TỔNG QUAN KIẾN TRÚC & MỤC TIÊU

### 1.1. Mục tiêu
- Huấn luyện mô hình sinh mã Python (`code`) để giải quyết các câu hỏi tính toán trên bảng biểu lộn xộn (CSV, Excel, SQLite) theo ngữ cảnh doanh nghiệp (`README.md`, schema) và quy tắc nghiệp vụ (`rulebook.md`).
- Tận dụng tối đa tài nguyên miễn phí của Kaggle: **2× GPU T4 (16GB VRAM mỗi card = 32GB VRAM)**.
- Đánh giá chất lượng mô hình sau khi train bằng hệ thống suy luận **vLLM** trên tập **Pilot 30 câu**, đo điểm theo công thức **Penalized Accuracy (PA)** của BTC:
  $$\text{PA} = \frac{1}{N} \left( N_{\text{correct}} \times 1.0 + N_{\text{abstain}} \times 0.0 - N_{\text{wrong}} \times 1.0 \right)$$

### 1.2. Thông số kỹ thuật huấn luyện (Hyperparameters)
- **Base Model:** `Qwen/Qwen2.5-Coder-7B-Instruct`
- **Phương pháp:** LoRA FP16 (`r=16`, `lora_alpha=32`, target toàn bộ attention + MLP layers).
- **Phân tán:** PyTorch FSDP (Fully Sharded Data Parallel) qua cấu hình Accelerate (`configs/accelerate_kaggle_2t4_sft.yaml`).
- **Context Length (`MAX_SEQ_LEN`):** `8192` tokens.
- **Batch Size:** `1 sample/GPU` × `2 GPUs` × `Gradient Accumulation 4` = **Effective Batch Size 8**.
- **Epochs & Learning Rate:** `3.0 epochs`, LR `1e-4` (Cosine schedule, warmup 5%).
- **Dữ liệu huấn luyện:** 890 mẫu chuẩn (`verified_sft_dataset.jsonl`), chỉ lưu `id`, `business_id`, `code` (prompt được dựng động từ raw data chỉ đọc để tránh rò rỉ đường dẫn local).

---

## 2. CHECKLIST TÀI NGUYÊN CẦN CHUẨN BỊ TRƯỚC KHI CHẠY

| Tài nguyên | Nguồn lấy / Vị trí | Ghi chú |
| :--- | :--- | :--- |
| **Input Bundle Zip** | `result/datamate_qwen7b_890_portable_train_eval_kaggle_input.zip` (có sẵn trong repo, ~126MB) | Tạo mới nếu cần: `python scripts/package_kaggle_890_eval.py` |
| **Base Model Weights** | Kaggle Dataset: `Qwen2.5-Coder-7B-Instruct` | Search trên Kaggle Dataset hoặc dùng bản shard safetensors chính thức |
| **Notebook** | `notebooks/02_train_sft_qwen7b_kaggle_2t4_890.ipynb` | Upload lên Kaggle Notebook mới |
| **Hugging Face Token** | Kaggle Secrets: Tạo Secret tên `HF_TOKEN` | Token cần quyền **Write** để tự động push adapter lên Hub |

---

## 3. CÁC BƯỚC THIẾT LẬP TRÊN KAGGLE (SETUP GUIDE)

### Bước 1: Tạo Kaggle Notebook mới
1. Mở Kaggle, tạo một Notebook mới.
2. Tại bảng điều khiển bên phải (**Notebook settings**):
   - **Accelerator:** Chọn **`GPU T4 x2`** *(BẮT BUỘC: Không chọn P100 hay T4 x1, FSDP cần đúng 2 GPU)*.
   - **Internet:** Bật **`Internet On`** *(BẮT BUỘC: Để tải thư viện và upload HF)*.
   - **Environment:** Chọn `Always use latest environment`.

### Bước 2: Thêm Secret `HF_TOKEN`
- Vào menu **Add-ons** $\rightarrow$ **Secrets** $\rightarrow$ Nhập:
  - **Label:** `HF_TOKEN`
  - **Value:** `<HuggingFace User Access Token có quyền Write>`
- Đánh dấu tick cho phép Notebook này truy cập secret `HF_TOKEN`.

### Bước 3: Thêm Inputs (Data & Model)
- Bấm **Add Input** $\rightarrow$ Upload file `datamate_qwen7b_890_portable_train_eval_kaggle_input.zip` làm một Private Dataset mới (đặt tên ví dụ: `datamate-qwen7b-890-input`).
- Bấm **Add Input** $\rightarrow$ Tìm kiếm và gắn dataset chứa trọng số `Qwen2.5-Coder-7B-Instruct` (đảm bảo bên trong có file `config.json` và `model.safetensors.index.json`).

### Bước 4: Import mã nguồn Notebook
- Import file `notebooks/02_train_sft_qwen7b_kaggle_2t4_890.ipynb` vào giao diện code của Kaggle.

---

## 4. QUY TRÌNH THỰC THI CHI TIẾT (CELL BY CELL)

Toàn bộ notebook gồm 25 cells (12 phần đánh số). Hãy chạy tuần tự theo các bước kiểm soát sau:

### Chặng 1: Kiểm tra tiền trạm (Preflight Checks — Cells 1 đến 12)
- **Cell 02 (Cấu hình):** 
  - Đặt `RUN_NAME = 'qwen7b_890_portable_fp16_lora'`.
  - Nếu có nhiều model weights trong Input, điền đường dẫn cụ thể vào `MODEL_DIR`. Mặc định để trống script sẽ tự quét.
  - Kiểm tra `nvidia-smi` xác nhận 2 card T4 đã sẵn sàng.
- **Cell 04 (Bundle & Data Check):**
  - Script tự kiểm tra mã SHA256 của file zip và dataset 890 mẫu. Nếu báo lỗi mismatch, kiểm tra lại bundle đã upload đúng file zip mới nhất chưa.
- **Cell 06 (Cài đặt môi trường):**
  - Cài thư viện theo `requirements-kaggle-sft.txt`. Tự động gỡ `torchao` để tránh xung đột với PEFT.
  - Xuất hiện thông báo xác nhận: `torch 2.6+`, `2 GPUs (7,5) 15 GiB`.
- **Cell 08 (Kiểm tra upload Hugging Face):**
  - Thực hiện upload thử một file probe nhỏ lên repo private `HF_REPO_NAME = 'Zalo-challenge'`.
  - **DỪNG LẠI NẾU BƯỚC NÀY LỖI:** Nếu fail ở đây (lỗi token, mạng), sửa ngay secret trước khi train để không bị mất trắng công sức.
- **Cell 10 (Kiểm tra Model Weights):**
  - Kiểm tra kiến trúc đúng chuẩn `qwen2` (hidden_size 3584, 28 layers) và đủ các shard file `model.safetensors`.
- **Cell 12 (Build SFT Dataset & Token Count):**
  - Dựng prompt hoàn chỉnh từ raw data chỉ đọc.
  - Tokenize toàn bộ 890 mẫu: xác nhận `records: 890` và `overlength: False` (tất cả đều nằm trong ngưỡng 8192 token).

### Chặng 2: Smoke Test & Huấn luyện (Cells 13 đến 18)
- **Cell 14 (Smoke Test — CỰC KỲ QUAN TRỌNG):**
  - Chạy thử đúng **2 optimizer steps** với những câu dài nhất.
  - Đồng thời kiểm tra tính năng lưu/khôi phục checkpoint.
  - **Quan sát log:** Phải thấy `peak_vram_gib` trên cả 2 GPU (thường khoảng 13.5 - 14.5 GiB / 15 GiB). Nếu không báo lỗi OOM và status là `passed`, bạn an toàn để train thật.
- **Cell 16 (Full SFT Training):**
  - Thời gian chạy ước tính: **~2.5 đến 3.5 giờ** trên 2× GPU T4.
  - Cứ mỗi 10 steps sẽ tự lưu checkpoint (giữ tối đa 2 checkpoint gần nhất để tránh đầy đĩa).
  - *Lưu ý phục hồi (Resume):* Nếu Kaggle bị disconnect giữa chừng:
    - Trong cùng phiên: Đặt `RESUME_FROM_CHECKPOINT = 'latest'` rồi chạy lại Cell 16.
    - Trong phiên mới: Thêm Output của phiên cũ làm Input cho phiên mới, điền đường dẫn checkpoint cụ thể vào `RESUME_FROM_CHECKPOINT`.
- **Cell 18 (Upload Final Adapter lên Hugging Face):**
  - Đẩy trực tiếp thư mục `final_adapter` (`adapter_model.safetensors`, `adapter_config.json`) lên Hugging Face Hub.
  - Kiểm tra trên web HF thấy commit thành công mới yên tâm.

### Chặng 3: Đánh giá Pilot & Đóng gói (Cells 19 đến 24)
- **Cell 20 (Cài runtime vLLM & Đăng ký cuSPARSELt):**
  - Tạo venv riêng tại `/tmp/datamate_vllm_eval_env` để cài `vllm==0.10.2` độc lập.
  - Tự động cài đặt `nvidia-cusparselt-cu12` và đăng ký `libcusparseLt.so.0` vào `/usr/lib` qua `ldconfig` (đã được fix sẵn trong notebook, tránh lỗi thiếu shared library khi vLLM import).
- **Cell 22 (Chấm 30 câu Pilot bằng vLLM trên 2×T4):**
  - Chạy suy luận với `tensor-parallel-size=2`, `enforce-eager`, `--max-model-len 8192` và tắt `--no-prefix-caching` (đã tối ưu sẵn cho giới hạn cứng 64KB Shared Memory của chip Turing T4).
  - Xem kết quả in ra dạng JSON:
    ```json
    {
      "correct": ...,
      "wrong": ...,
      "abstain": ...,
      "penalized_accuracy": ...,
      "seconds_per_question": ...
    }
    ```
  - *Lưu ý:* 14/30 câu này có nằm trong tập train (đây là tập pilot kiểm tra độ khớp và tính ổn định code, không phải held-out test hoàn toàn).
- **Cell 24 (Đóng gói kết quả):**
  - Tự động nén adapter + file log + file json kết quả thành `<RUN_NAME>_results.zip`.
  - Click vào link tải trực tiếp (`FileLink`) để lưu về máy cá nhân.

---

## 5. NHỮNG BẪY KỸ THUẬT & CÁCH XỬ LÝ (TROUBLESHOOTING)

### 1. Tràn dung lượng ổ đĩa Kaggle (`No space left on device`)
- **Nguyên nhân:** Kaggle chỉ cấp tối đa 20GB dung lượng cho `/kaggle/working`. Checkpoint của mô hình 7B rất nặng nếu lưu nhiều bản.
- **Giải pháp:**
  - Script đã cấu hình chỉ giữ tối đa 2 checkpoint gần nhất + checkpoint cuối.
  - Môi trường vLLM được đưa vào `/tmp` (RAM disk/tmpfs) thay vì working directory.
  - Tuyệt đối không copy raw data từ Input sang Working.

### 2. Tràn bộ nhớ GPU (CUDA Out-Of-Memory — OOM)
- **Nguyên nhân:** Seq len vượt quá 8192 hoặc gradient accumulation quá lớn.
- **Giải pháp:**
  - Giữ nguyên `MAX_SEQ_LEN = 8192` và batch size `1 per GPU`.
  - Kiểm tra cờ `expandable_segments:True` đã được set ở Cell 02.
  - Nếu cần giảm VRAM, hạ `MAX_SEQ_LEN` xuống `7168` hoặc `6144`.

### 3. Lỗi upload Hugging Face (`401 / 403 Forbidden`)
- **Nguyên nhân:** Token HF chưa bật quyền `Write`, hoặc nhập sai tên Secret `HF_TOKEN`.
- **Giải pháp:**
  - Vào HuggingFace $\rightarrow$ Settings $\rightarrow$ Access Tokens $\rightarrow$ Tạo token kiểu `Write`.
  - Cập nhật lại trong Kaggle Secret và restart lại kernel.

### 4. Nếu đã train xong nhưng chỉ muốn Upload lại hoặc Đánh giá lại
- Dùng notebook chuyên dụng: [`notebooks/upload_trained_qwen7b_to_hf.ipynb`](../notebooks/upload_trained_qwen7b_to_hf.ipynb).
- Hoặc trong notebook chính: điền đường dẫn adapter vào `EVAL_ADAPTER_DIR`, sau đó chạy từ Cell 18 hoặc Cell 20 (bỏ qua các cell smoke/train).

---

## 6. TIÊU CHUẨN ĐẦU RA BÀN GIAO (DELIVERABLES)

Sau khi hoàn thành đợt train, người tiếp nhận cần bàn giao lại cho team:
1. **Link Hugging Face Repository:** Chứa weights adapter đã train (`adapter_model.safetensors`, `adapter_config.json`).
2. **File kết quả ZIP:** `<RUN_NAME>_results.zip` chứa đầy đủ file log huấn luyện, đồ thị loss và báo cáo pilot.
3. **Báo cáo chỉ số Pilot 30 câu:**
   - Điểm **Penalized Accuracy (PA)** đạt được.
   - Tỷ lệ câu Đúng / Sai / Từ chối (`correct` / `wrong` / `abstain`).
   - Thời gian suy luận trung bình mỗi câu (`seconds_per_question`).

---
> 💡 *Nếu có thắc mắc trong quá trình chạy, hãy tham khảo tài liệu chi tiết tại [`docs/KAGGLE_QWEN7B_890_PORTABLE.md`](KAGGLE_QWEN7B_890_PORTABLE.md) hoặc xem lại các rule bắt buộc tại [`AGENTS.md`](../AGENTS.md).*
