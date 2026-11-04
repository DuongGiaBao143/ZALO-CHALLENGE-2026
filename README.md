# DataMate — Qwen7B

Agent trả lời câu hỏi tiếng Việt trên CSV, Excel và SQLite bằng cách sinh Python, chạy code, đọc kết quả/lỗi rồi trả đáp án có kiểu dữ liệu.

Pipeline hiện tại dùng **Qwen/Qwen2.5-Coder-7B-Instruct**. LoRA được nạp khi đánh giá bản đã fine-tune; bước sinh dữ liệu mặc định vẫn dùng pretrained. Model weights, artifacts và các thử nghiệm cũ nằm ngoài phạm vi Git.

## Luồng làm việc

| Bước | Notebook | Công việc |
|---|---|---|
| 1 | [Sinh và lọc SFT](notebooks/01_generate_sft_dataset_qwen7b.ipynb) | Nhận folder, README, schema, câu hỏi/ngày mốc; sinh/chạy code, lọc bằng đáp án train |
| 2 | [Train LoRA](notebooks/02_train_sft_qwen7b_lora.ipynb) | Huấn luyện adapter, tính loss trên assistant completion cuối, lưu adapter và log |
| 2 — Kaggle | [Train 208 mẫu trên 2×T4](notebooks/02_train_sft_qwen7b_kaggle_2t4_208.ipynb) | FP16 LoRA + FSDP, kiểm tra token, checkpoint/resume; xem [hướng dẫn](docs/KAGGLE_QWEN7B_208.md) |
| 3 | [Suy luận với adapter](notebooks/03_run_inference_sft_qwen7b.ipynb) | Nạp base weights + adapter, chạy agent và xuất JSONL |
| Đối chứng | [Pilot pretrained](notebooks/datamate_baseline_7b_pilot.ipynb) | Đánh giá một mẫu nhỏ bằng model gốc |

Notebook cần repo/source đi kèm, dữ liệu và đường dẫn weights/Drive phù hợp runtime. Các đường dẫn `/content/...` trong config dành cho Colab, cần chỉnh khi dùng môi trường khác. Cell đang mở từ notebook cũ không tự cập nhật khi file trên Drive thay đổi.

Đầu vào bước 1 gồm chỉ dẫn Python/JSON ngắn, `BUSINESS_DIR`, README, file/sheet, mọi cột/dtype, câu hỏi và `as_of_date`. Sheet cùng cấu trúc được gộp schema. Code đọc rulebook/lịch và dữ liệu thật khi cần; gold không nằm trong prompt. Xem [đặc tả bước 1](docs/STAGE1_FOLDER_SCHEMA.md).

`verified_sft_dataset.jsonl` ở gốc repo chỉ giữ `id`, `business_id`, `code`. Hai script train tự dựng messages từ dữ liệu BTC được chỉ định bằng `--data-dir` (mặc định `data/train`); prompt dùng biến runtime thay cho đường dẫn máy. Có thể dùng `scripts/build_sft_dataset.py` để dựng trước messages rồi train mà không mang raw data. Bundle Kaggle 890 portable mang dataset gọn và raw train read-only; notebook build context một lần trên Kaggle trước khi FSDP. Xem [hướng dẫn 890 + HF](docs/KAGGLE_QWEN7B_890_PORTABLE.md). Sửa dataset không cập nhật adapter đã train hay các ZIP/Input Kaggle cũ.

Runtime hỗ trợ vòng code → observation/lỗi → sửa/tính tiếp có giới hạn lượt. Kết quả JSONL có dạng:

```json
{"id":"q_example","type":"number","answer":123}
```

`unanswerable` dành cho câu thiếu căn cứ dữ liệu; `abstain` dành cho việc agent chủ động từ chối. Xem quy tắc kiểu đáp án và chấm local trong [docs/evaluation.md](docs/evaluation.md).

## Cấu trúc

```text
notebooks/             Colab: sinh SFT, train, inference và pilot
configs/               Cấu hình Qwen7B
src/agent/             Prompt, backend, vòng chạy code và giao thức
src/profiler/          Schema CSV/XLSX/SQLite và README
src/time_resolver/     Ngày mốc và ngữ cảnh dùng chung
src/postprocess/       Chuẩn hóa đáp án, số và ngày tiếng Việt
src/eval/              Bộ chấm local
src/coder_training/    Collector/helper được bộ sinh dữ liệu tái sử dụng
scripts/               CLI sinh SFT, train, suy luận, chấm và tạo pilot
tests/                 Test CPU, giao thức, dữ liệu và notebook
docs/                  Tài liệu cuộc thi và đặc tả bước 1
data/                  Dữ liệu BTC — chỉ đọc
result/, tmp/          Artifacts/cache/kho lưu local — bị Git ignore
eval_gold/             Gold pilot local — bị Git ignore
```

## Chạy local

Cài dependency xử lý dữ liệu từ `requirements.txt`. GPU inference/training còn cần stack phù hợp; tham khảo notebook và `requirements-gpu.txt`. Cài dependency thành công chưa chứng minh GPU/Docker đã được kiểm chứng.

```bash
python -m pip install -r requirements.txt
python -m pytest tests -q --basetemp tmp/pytest-local
python scripts/select_pilot_subset.py
```

Lệnh chọn pilot ghi câu hỏi/manifest vào `result/baseline_7b_pilot/`, gold vào `eval_gold/`; không sửa dữ liệu gốc. `pytest --basetemp` sử dụng thư mục test tạm, không chọn thư mục chứa artifacts cần giữ.

Inference bằng config đã trỏ tới checkpoint local:

```bash
python scripts/run_inference.py --config configs/baseline_7b_a100.yaml --data-dir data/train --questions-file result/baseline_7b_pilot/pilot_questions_30.jsonl --output result/pilot/submission.jsonl
python scripts/evaluate_local.py --pred result/pilot/submission.jsonl --gold eval_gold/pilot_gold_30.jsonl
```

Chỉ chấm với gold của đúng tập ID đã chạy. Dry-run chỉ kiểm tra I/O; khớp gold không tự chứng minh code đúng nghiệp vụ trên dữ liệu khác.

## Dữ liệu và đóng gói

- `data/` chỉ đọc: không sửa, đổi tên hoặc di chuyển file gốc. Một số dữ liệu đã được theo dõi từ lịch sử repo; `.gitignore` không tự bỏ chúng khỏi Git.
- Weights, adapter, checkpoint, log và SFT sinh ra nằm ngoài Git. Gold phải tách khỏi vùng code sinh ra được phép đọc.
- Runner là subprocess có timeout; cách ly mạng, filesystem và tài nguyên cần được thiết lập ở môi trường thực thi.
- `Dockerfile` và `predict.sh` là khung inference offline. Chỉ coi sẵn sàng nộp khi đã đóng gói weights và kiểm chứng trên môi trường yêu cầu.

Tài liệu tham khảo: [mô tả](docs/description.md), [dữ liệu](docs/data.md), [đánh giá](docs/evaluation.md), [thể lệ](docs/rule.md), [nộp bài](docs/submission_guidance.md). Đối chiếu tài liệu BTC khi chốt cách nộp chính thức.
