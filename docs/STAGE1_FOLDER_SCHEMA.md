# Giai đoạn 1: sinh SFT Qwen7B với README và schema

Notebook: `notebooks/01_generate_sft_dataset_qwen7b.ipynb`.

Đầu vào model gồm một chỉ dẫn ngắn về việc sinh/chạy Python và giao thức kết quả, sau đó là:

```text
BUSINESS_DIR: biến đường dẫn do môi trường thực thi cấp; dùng trực tiếp, không gán đường dẫn tuyệt đối.
Files: <tên các file>
README:
<nguyên văn README>
Schema:
<file / sheet hoặc bảng>
<tên cột>: <dtype>, ...
Quy tắc nghiệp vụ: RULEBOOK_PATH (đọc mục liên quan khi cần).
Lịch âm-dương: CALENDAR_PATH.
as_of_date: <ngày tham chiếu>
Câu hỏi: <nguyên văn câu hỏi>
```

Không đưa bảng dữ liệu mẫu, unique values, date ranges, danh sách mọi khoảng thời gian, toàn văn rulebook hay checklist lặp vào prompt. Giữ tất cả cột/dtype; các sheet có cùng schema/dtype/header/status được gộp tên sheet và chỉ ghi cấu trúc một lần. Sheet khác dtype/header vẫn hiển thị riêng. Lỗi đọc và Excel header candidate vẫn có mặt để model không hiểu nhầm dữ liệu hỏng thành dữ liệu trống.

Dataset gọn ở gốc repo, `verified_sft_dataset.jsonl`, chỉ lưu `id`, `business_id`, `code` (Python thuần, không có code fence). Khi train trực tiếp file này, truyền `--data-dir` tới tập train của BTC trên máy đang chạy: trainer tra câu hỏi/ngày mốc theo ID, đọc README/schema và dựng messages trong RAM. Không đọc gold để dựng prompt, không chạy code mẫu khi SFT. Prompt train và inference dùng chung formatter và không chứa vị trí thư mục của máy.

Nếu chỉ muốn mang dataset đã có đủ context lên máy train, chạy bước build trước:

```bash
python scripts/build_sft_dataset.py --input verified_sft_dataset.jsonl --data_dir data/train --output result/sft_portable_20261104/sft_train_ready.jsonl
```

File sinh ra có messages và có thể train mà không cần raw data. Bundle Kaggle 890 portable chứa file gọn và raw train read-only để notebook tự dựng messages trên Kaggle. Khi evaluate vẫn cần dữ liệu thật và runner sẽ cấp `BUSINESS_DIR`, `RULEBOOK_PATH`, `CALENDAR_PATH`. Các bộ trace sinh SFT cũ giữ nguyên để truy vết; không dùng chúng thay dataset gọn mà không kiểm tra prompt/code.

README được giữ nguyên, nên doanh nghiệp có README dài/nhiều cột vẫn có prompt dài hơn. Không cắt lén thông tin để đạt một con số token cố định. Model có thể chạy code xem giá trị mẫu/quy tắc rồi nhận observation; lần sinh context này vẫn dùng tối đa hai lượt như script trước. Gold chỉ dùng chấm kết quả ngoài prompt. Khớp gold chưa chứng minh logic đúng tổng quát.

Thư mục mới: `result/sft_dataset_qwen7b_folder_schema_v1/`; backup dataset: `/content/drive/MyDrive/datamate_sft_backup_qwen7b_folder_schema_v1/`. Dataset và log có `prompt_format=folder_readme_schema_v1`. Không trộn vào 91 mẫu cũ. CLI mặc định cho context generation cũng chuyển sang `result/sft_folder_schema_v1/`; nhánh question-only có giao diện riêng.

Cell chạy trong notebook tự cập nhật các file source cần thiết từ thư mục dự án Drive nếu đang dùng workspace local, dùng tiến trình Python mới, in log trực tiếp và dừng khi lệnh lỗi. Ngân sách đầu ra tăng từ 650 lên tối đa 2048 token để giảm nguy cơ cắt ngang code; không bắt model sinh đủ 2048 token. Chưa thay đổi batch size hoặc chạy GPU trong lần sửa này.

Prompt dùng chung với runtime và script build SFT, giúp tránh một bên dùng schema tối giản còn bên kia nhét full rulebook. Đo độ dài ký tự và ví dụ được lưu tại `result/stage1_prompt_measurement.json` và `result/stage1_prompt_example.txt` sau kiểm tra local; không coi số ký tự là số token hay kết quả chất lượng model.

Đo bằng profiler thật trên 6 doanh nghiệp của pilot (30 câu): tổng system + user prompt nhỏ nhất 2779 ký tự, trung vị 5077, lớn nhất 9345. Đây là số ký tự của đầu vào ban đầu; chưa tính lịch sử các lượt sau. Không cam kết một ngân sách token cố định khi vẫn giữ nguyên README và mọi cột/dtype.
