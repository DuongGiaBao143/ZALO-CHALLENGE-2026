# Kaggle Qwen7B: 890 mẫu gọn và upload HF

## Chạy training mới

1. Upload `result/datamate_qwen7b_890_portable_train_eval_kaggle_input.zip` thành private Kaggle Dataset và Add Input. Dùng bundle revision `portable-sft-hf-v3`; không trộn với bundle 890 cũ.
2. Import `notebooks/02_train_sft_qwen7b_kaggle_2t4_890.ipynb`, gắn weights Qwen2.5-Coder-7B-Instruct, chọn T4 ×2 và bật Internet.
3. Thêm/bật Kaggle Secret `HF_TOKEN` có quyền write. Mặc định repo private `username/Zalo-challenge`. Preflight upload một file probe để kiểm tra quyền ghi trước khi train.
4. Notebook đọc dataset `id/business_id/code`, tra câu hỏi/ngày mốc và đọc README/schema từ `training/train` trong Input chỉ đọc. Bước build chạy một lần, ghi messages vào Working rồi mới tokenize/FSDP. Không đọc gold hoặc chạy code mẫu khi SFT. Prompt không chứa đường dẫn máy; runner cấp biến đường dẫn khi inference.
5. Sau full train, chạy cell upload final adapter trước khi cài vLLM/chấm pilot. Bước này chạy trong tiến trình online mới và chỉ báo `uploaded` khi hai file adapter có trên commit HF.
6. Save Version/Output để giữ checkpoint resume. ZIP cuối chỉ chứa adapter và kết quả nhẹ, không nhân bản optimizer checkpoints.

Bundle chứa raw train của 24 shop cho SFT và 6 shop cho pilot; không chứa train gold trong vùng dựng context. Pilot gold nằm riêng tại `evaluation/pilot_gold_30.jsonl` chỉ dùng khi chấm. Có 14/30 pilot ID giao với SFT.

## Upload lại adapter đã train xong

Import `notebooks/upload_trained_qwen7b_to_hf.ipynb`, bật Internet và `HF_TOKEN`, rồi chạy cell duy nhất. Không cần GPU hoặc source bundle. Mặc định adapter là:

```text
/kaggle/working/datamate_qwen7b_890/runs/qwen7b_890_fp16_lora/train/final_adapter
```

Nếu phiên đã kết thúc, Add Input Output cũ và sửa `ADAPTER_DIR` tới `final_adapter` trong Input đó. Notebook chỉ có thể upload file còn tồn tại; sửa notebook không khôi phục được file máy ảo đã mất.

Với run đã có `completed.json` trong Working, cell dọn riêng snapshot upload tạm `.train-hub-staging`/`.smoke-hub-staging`. Giữ nguyên adapter và checkpoint resume. Không dọn Input read-only hoặc đường dẫn symlink ra ngoài run.

## Chẩn đoán lỗi upload và đĩa

`ValueError` trong log cũ không chứa nội dung exception nên chưa đủ xác định nguyên nhân upload. Bản mới ghi thêm message đã che token và HTTP status nếu có. `401/403` cần kiểm tra token/quyền repo; lỗi mạng được thử lại có giới hạn. Không báo thành công chỉ vì file tồn tại local.

Backup nền giữ tối đa một upload đang chạy, bỏ qua checkpoint trung gian khi bận và không tạo snapshot nếu thiếu phần dung lượng dự phòng. Final adapter luôn được thử upload riêng trong notebook. Pip không giữ cache; raw data không bị chép từ Input sang Working. Đây là các biện pháp giảm chiếm đĩa, không bảo đảm phiên vốn đã đầy đĩa có thể tiếp tục mà không giải phóng dung lượng.

HF đọc cấu hình môi trường khi import; vì vậy bước upload dùng tiến trình mới với offline mode tắt trước import: https://huggingface.co/docs/huggingface_hub/main/package_reference/environment_variables

Kiểm tra local gồm test upload bằng API giả lập, snapshot bị xoay/xóa, hàng đợi chậm, thiếu đĩa, che token, notebook JSON/Python và dựng context sau khi đổi thư mục. Chưa chạy GPU hoặc upload thật bằng Kaggle Secret trong lần sửa này.
