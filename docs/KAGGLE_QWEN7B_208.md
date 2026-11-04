# Qwen7B SFT với 208 mẫu trên Kaggle 2×T4

Notebook: `notebooks/02_train_sft_qwen7b_kaggle_2t4_208.ipynb`.

1. Upload gói `datamate_qwen7b_208_kaggle_input.zip` thành **private Kaggle Dataset**, rồi Add Input vào notebook. Kaggle giải nén gói khi tạo Dataset.
2. Import notebook `.ipynb`. Chọn GPU **T4 ×2**, bật Internet để cài dependencies và gắn weights **Qwen2.5-Coder-7B-Instruct** qua Add Input. Weights không có trong gói nhỏ này.
3. Chạy từ đầu. Notebook tìm bundle và checkpoint model trong `/kaggle/input`; nếu có nhiều model phù hợp thì điền `MODEL_DIR`.
4. Cell kiểm tra token chạy trước khi nạp weights. Chạy smoke 2 optimizer steps, sau đó chạy cell train đầy đủ.
5. Chọn **Save Version → Save & Run All** để lưu các file `/kaggle/working` thành Output của phiên chạy. Trước khi kết thúc một phiên interactive, tải ZIP kết quả hoặc lưu Output; file trên máy ảo không tự thành bản sao vĩnh viễn.

Dataset là `result/sft_merged_folder_schema_20261102/sft_train_ready.jsonl`: 208 ID riêng biệt, cùng `folder_readme_schema_v1`. Giữ nguyên 73 hội thoại 5 lượt; chỉ assistant cuối có loss, kể cả khi lượt assistant đầu là code sai. Không thực thi code sinh ra khi SFT nên không cần upload raw business data hay gold để train.

Đã đo với tokenizer Qwen thật: 208/208 mẫu hợp lệ, toàn hội thoại dài 1.086–6.766 token. Giới hạn 8.192 token giữ đủ mẫu. Nếu dataset/tokenizer thay đổi mà vượt giới hạn, notebook ghi báo cáo rồi dừng, không cắt hoặc loại mẫu âm thầm.

Cấu hình khởi đầu: frozen base FP16, FSDP1 FULL_SHARD qua 2 GPU; LoRA r16/alpha32/dropout0.05 ở q/k/v/o/gate/up/down; microbatch 1/GPU, accumulation 4, effective batch 8; 3 epochs, LR 1e-4, seed42. Đây là cấu hình ban đầu, chưa có benchmark chất lượng hay bằng chứng tối ưu trên hai T4. Không dùng BF16 hoặc QLoRA. FSDP wrap riêng frozen và trainable leaves theo [PEFT FSDP](https://huggingface.co/docs/peft/v0.17.0/accelerate/fsdp). SDPA trên T4 dùng kernel tiết kiệm bộ nhớ; không cài FlashAttention2. Chỉ tính logits tại vị trí có loss để tránh tạo tensor vocabulary lớn cho toàn prompt.

Notebook lưu `train.log`, `metrics.jsonl`, `dataset_report.json`, `run_config.json`, thống kê peak VRAM hai rank, `final_adapter/` và checkpoint mỗi 10 optimizer steps, giữ 2 checkpoint gần nhất. Checkpoint chứa adapter, optimizer, scheduler, scaler, RNG và Trainer state; không nhân bản frozen weights 7B.

## Xem log từ máy local và backup khi chạy nền

Chạy PowerShell ở repo:

```powershell
./scripts/watch_kaggle_sft.ps1
```

Script theo dõi `crinkk/02-train-sft-qwen7b-kaggle-2t4-208`, hiển thị stdout/stderr khi Kaggle cung cấp log và ghi thêm vào `result/kaggle_live_monitor/train-live.log`. Kaggle CLI cần đăng nhập; máy local phải còn chạy để xem log trực tiếp. Việc train Save & Run All tiếp tục trên Kaggle dù đóng terminal. Có thể dùng trực tiếp `kaggle kernels logs crinkk/02-train-sft-qwen7b-kaggle-2t4-208 --follow`. Xem [Kaggle CLI](https://github.com/Kaggle/kaggle-cli/blob/main/skills/references/kernels.md).

Để backup cả lúc máy local tắt, thêm **Kaggle Secret `HF_TOKEN` có quyền write** và bật quyền dùng secret cho notebook. Mặc định `HF_REPO_NAME='Zalo-challenge'`. Notebook lấy username của token, tạo repo model **private** `<username>/Zalo-challenge`; nếu repo cùng tên đang public thì dừng để tránh upload nhầm. Token không ghi trong notebook/log.

Rank 0 upload từng checkpoint hoàn chỉnh và final adapter trong thread nền lên `runs/<RUN_NAME>/<UTC timestamp>/train/` (smoke có nhánh riêng). Snapshot riêng tránh checkpoint rotation xóa file đang upload. Log có `[HF backup] queued/uploaded/upload_failed`; sự cố upload giữ lại file local và không cố tình làm mất tiến trình train. Cuối lượt train đợi các upload đã xếp hàng hoàn tất. Đặt `HF_REPO_NAME=''` nếu chỉ cần log, không dùng Hub. Gói ZIP và notebook mới phải được cập nhật cùng nhau; bundle cũ không chứa module backup.

Code mới chỉ có hiệu lực ở Save Version tiếp theo, không được chèn vào phiên Save & Run All đang chạy. CLI xem được log phiên hiện tại mà không cần sửa phiên đó. Chỉ trạng thái `uploaded` mới chứng minh artifact đã lên Hub; không suy từ việc checkpoint tồn tại local.

Để resume trong phiên hiện tại, đặt `RESUME_FROM_CHECKPOINT='latest'`, giữ nguyên settings rồi chạy lại cell train. Để resume từ phiên khác, gắn Output cũ như Input, đặt biến này thành đường dẫn đầy đủ tới `checkpoint-N` có `checkpoint_complete.json`. Giữ cùng dataset, model Input/path, source và versions. Không đổi cấu hình giữa lần chạy và resume; manifest kiểm tra checksum các file state. Chỉ dùng checkpoint mình tạo vì các state optimizer/RNG là dữ liệu PyTorch pickle.

`final_adapter/` là adapter PEFT chuẩn, dùng với base Qwen7B trong pipeline suy luận hiện tại. Notebook chỉ train: không báo PA. Tập pilot 30 câu hiện có 4 ID nằm trong bộ SFT, nên điểm trên cả 30 câu không phải đánh giá hoàn toàn trên câu chưa học.

Kiểm tra local gồm tokenizer thật, loss masking, so sánh loss/gradient khi chỉ giữ logits completion, và adapter/optimizer resume bằng Qwen nhỏ trên CPU. Chưa xác minh thời gian, VRAM thực tế hoặc OOM trên Kaggle 2×T4; cell smoke trên phần cứng của người chạy là bước kiểm tra đó.
