# Context của pilot Ornith + OpenCode

Mục tiêu là đánh giá một agent dưới 15B cho DataMate bằng câu hỏi tiếng Việt nguyên văn. Pilot dùng Ornith 1.5 9B để hiểu câu hỏi và gọi tool. Hai tool có tham số xử lý dữ liệu bằng Python đã có trong repo. Công việc tiếp theo là viết notebook eval trên Kaggle T4 ×2. [Handoff cho Antigravity](ORNITH_OPENCODE_KAGGLE_HANDOFF.md)

## Luồng đã chạy ở local

1. Launcher đọc record trong `data/train/questions.jsonl` và chọn gói dữ liệu theo `business_id`. Chế độ `--structured-tools --question-only` gửi đúng `question + "\n\nas_of_date: " + as_of_date`. OpenCode nhận full `rulebook.md` của split qua system instructions. README và schema của shop được lấy qua tool trong lượt giải.
2. OpenCode chạy headless trong Docker bằng `opencode run --format json`. Nó gửi yêu cầu tới endpoint OpenAI-compatible của Ollama trên máy host. Ollama chạy Ornith và trả tool calls. OpenCode gọi tool trong container rồi đưa kết quả về cho model.
3. OpenCode cho gọi `read`, `inspect_table` và `aggregate` trong chế độ `--question-only`. Container local gắn CSV, README và rulebook chỉ đọc. Docker giữ môi trường chạy OpenCode và tool, còn Ollama chạy model trên host.
4. `inspect_table` dùng `explore_data` để đọc schema và giá trị thực tế. Gọi với `file=null, column=null` để tìm CSV. Với một file, tool trả ngay schema. Với nhiều file, tool trả danh sách để model chọn tiếp.
5. `aggregate` hiện có đúng một phép tính đã thử cho CSV là `count_distinct` theo ngày hoặc khoảng ngày trọn vẹn. Model chọn file, cột ngày, cụm thời gian, cột cần đếm, cột trạng thái và các nhãn cần loại. Python dùng `resolve_date`, `load_clean_df` và `parse_vn_date`. Tool kiểm tra nhãn theo dữ liệu thật và loại cả mã có dòng mang trạng thái được chỉ định trong khoảng đã lọc.
6. OpenCode xuất sự kiện `tool_use`, `step_finish` và đoạn `text` của câu trả lời cuối. Tool trả một object có `type` và `answer` cùng số dòng, số mã trước lọc và số mã bị loại. Model chốt ở một lượt riêng nên kết quả tool và câu trả lời người dùng nhận có thể khác nhau.

[Launcher local](../tmp/run_opencode_sandbox.py) · [Python tool bridge](../tmp/opencode-structured/bridge.py) · [Khai báo inspect_table](../tmp/opencode-structured/tools/inspect_table.js) · [Khai báo aggregate](../tmp/opencode-structured/tools/aggregate.js) · [JS gọi Python](../tmp/opencode-structured/run.js)

## Cấu hình dùng để đối chiếu

| Thành phần | Giá trị đã kiểm tra ở local |
| --- | --- |
| OpenCode | `1.19.5` |
| Ollama | `0.40.7`, runner `llamacpp` |
| Base tag | `ornith15-datamate-pilot-8k:latest`, parent `ornith-1.5:9b`, GGUF `Q4_K_M`, 9.0B, 6.550.813.701 bytes |
| Digest của base tag | `57ad8bec8adf0a704a07a26adb2abf9edae310ba0fd3cef575d02dac1af69bb5` |
| Hai blob trong kết quả `ollama show --modelfile` | `852922174ee4f76621df26105333f1dfe2171cdfb60ebe5a4b013836681a8a77` và `2635637dd72b4d39a97331373a73366b69a0a6a14151b2a1da0a97b311e2461f` |
| SHA-256 của chat template từ `/api/show` | `f55f52930aa8bf44ab5cb85f99370fcc3c56e9a85640b812086d5330bce5d86b` |
| Tham số của lượt structured hiện hành | `num_ctx=16384`, `seed=42`, `presence_penalty=0`, `num_batch=128`, `temperature=0` cho baseline và `0.4` cho lượt so sánh |
| Giới hạn OpenCode | Context 16.384, tối đa 2.048 token đầu ra mỗi lượt gọi model, tối đa 6 lượt agent, auto-compaction tắt |
| Python trong Docker local | Python `3.14.10`, pandas `3.0.3`, NumPy `2.4.6` |
| Snapshot helper của Khanh Linh | `efee164a857736181f9dcd0ebf023f47b11e8844`, được export vào `tmp/opencode-structured/src/` |

Tên base tag có chữ `8k` vì tham số gốc là 8.192. Launcher tạo tag tạm từ base tag để đặt context thực tế phía Ollama lên 16.384. Tag tạm kế thừa seed, chat template và các tham số còn lại.

## Kết quả đã thấy

Các câu dưới đây thuộc split train và dùng để smoke test. Điểm trong bảng là điểm của **câu trả lời cuối**, sau khi quy một JSON number thuần thành kiểu `number`.

| Shop và mã câu | Chế độ | Kết quả tool | Câu trả lời cuối và điểm |
| --- | --- | --- | --- |
| `biz_101` · `q_0cb7c9b93048` | Câu gốc + ngày + README/schema tự động, temp 0 | 38 mã, loại 1, còn 37 | `{"type":"number","answer":37}`, +1. [Log](../tmp/opencode-ornith15-biz101-structured-t0.jsonl) |
| `biz_110` · `q_05f70ec18809` | Câu gốc + ngày + README/schema tự động, temp 0 | Quý 2/2026, 5.909 mã, loại 137, còn 5.772 | `5772`, +1 khi chuẩn hóa kiểu số. Với trần 1.024, lần chạy trước hết token trước khi gọi tool. [Log 1.024](../tmp/opencode-ornith15-biz110-structured-t0.jsonl) · [Log 2.048](../tmp/opencode-ornith15-biz110-structured-t0-2048.jsonl) |
| `biz_125` · `q_5c19a3193881` | Prompt ngắn, temp 0 | Tự tìm CSV, đọc README, sửa tham số cột bị lỗi, tra nhãn rồi đếm 42 mã, loại 1, còn 41 | `41`, +1 khi chuẩn hóa kiểu số. [Log](../tmp/opencode-ornith15-biz125-question-only-t0.jsonl) |
| `biz_125` · `q_5c19a3193881` | Cùng prompt ngắn, temp 0.4 | Tự sửa nhãn, cuối cùng loại đúng `Huỷ đơn` và `Đã trả hàng`, tool ra 41 | Trống, `abstain`, 0. Lượt 6 ghi `reason=stop`, 1 token đầu ra và 0 sự kiện `text`. [Log](../tmp/opencode-ornith15-biz125-question-only-t04.jsonl) |

Hai lượt `biz_125` nhận cùng user prompt dưới đây.

```text
Tính riêng ngày hôm nay, cửa hàng bán được bao nhiêu đơn hàng?

as_of_date: 2025-03-28
```

Bản cho model tự viết Python từng mắc lỗi import thừa, đoán nhãn và so kiểu ngày không khớp. Hai custom tool có tham số được dùng trong pilot để đo riêng khả năng chọn cột, ngày và nhãn. Handoff Kaggle giữ pilot làm đối chứng và yêu cầu thêm `run_python` cho eval agent để Ornith có thể tự viết và chạy code khi cần. Đường gọi `run_python` qua OpenCode, độ phủ ngoài CSV `count_distinct`, PA trên shop holdout và khả năng chạy 16K trên T4 vẫn cần đo. [Yêu cầu cho notebook](ORNITH_OPENCODE_KAGGLE_HANDOFF.md#2-tool-và-prompt)

## Hợp đồng chấm và các file cần mang theo

Record dự đoán dùng `id`, `type`, `answer`, theo `docs/data.md` và `SubmissionItem`. Với câu trên, record kiểu số hợp lệ là `{"id":"q_5c19a3193881","type":"number","answer":41}`. `type` tham gia chấm điểm. Handoff cho phép điền kiểu còn thiếu từ kết quả tool đã xác thực nếu giá trị model chốt khớp. Final trống được ghi là `abstain` trong baseline. [Quy tắc normalize trong handoff](ORNITH_OPENCODE_KAGGLE_HANDOFF.md#4-chấm-đúng-câu-trả-lời-cuối) · [Định dạng submission](data.md#51-file-kết-quả-submissionjsonl) · [Đánh giá](evaluation.md) · [SubmissionItem](../src/schemas.py)

`tmp/` bị Git ignore. Khi Antigravity đọc cùng checkout, các đường dẫn trên trỏ thẳng tới code và log đã chạy. Nếu dùng checkout khác, cần chuyển các file prototype trong `tmp/opencode-structured/` và launcher `tmp/run_opencode_sandbox.py`. Snapshot `src/` có thể tái tạo bằng `git archive` từ commit đã ghi trong bảng. Weights và các layer Ollama là đầu vào riêng cần chuẩn bị.
