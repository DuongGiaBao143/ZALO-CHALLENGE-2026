# Handoff cho Antigravity — Notebook eval Ornith + OpenCode trên Kaggle T4 ×2

Viết notebook `notebooks/Evaluate_Ornith_OpenCode_Kaggle_2T4.ipynb` cho DataMate. Mục tiêu là chạy cùng agent trên Kaggle và đo kết quả bằng scorer của repo. Đọc luồng local, các phiên bản đã xác minh và log từng ca trước khi triển khai. [Context của pilot](ORNITH_OPENCODE_CONTEXT.md)

## 1. Runtime cần tái lập

```text
Kaggle Notebook
  Runner Python → OpenCode CLI → Ollama trên loopback → Ornith
                     ↕ tool calls và kết quả
                 read / inspect_table / aggregate / run_python → gói dữ liệu của shop
  Runner Python → trace, dự đoán chuẩn hóa → scorer DataMate
```

- Dùng môi trường có sẵn của Kaggle làm sandbox. Chạy OpenCode, Ollama và tool Python trực tiếp trong notebook. Phần cần chuyển từ launcher Windows là cấu hình OpenCode, khâu chọn shop, prompt và logging. Phần Docker Desktop, bind mount Windows, `host.docker.internal`, `setpriv` và `iptables` chỉ mô tả luồng local.
- Ollama lắng nghe trên loopback của phiên Kaggle. Cấu hình provider OpenCode `@ai-sdk/openai-compatible` trỏ đến `http://127.0.0.1:11434/v1` hoặc port riêng của worker. Dùng `opencode run --format json` để thu event theo từng câu.
- Bắt đầu từ OpenCode `1.19.5`, Ollama `0.40.7` và đúng bản GGUF `Q4_K_M` của base tag `ornith15-datamate-pilot-8k:latest`. Đóng gói/import model dưới dạng Kaggle Input với manifest và các blob nó tham chiếu, hoặc dựng lại từ đúng layer và chat template. Kiểm tra digest/sha trong context. Tag tạm cho 16K có thể mang digest khác vì đổi tham số. Ghi rõ nguồn model và phiên bản thực tế trong manifest. Khi input model còn thiếu, cell preflight báo chính xác nội dung cần attach.
- Đọc nguồn ở `/kaggle/input` và ghi file sinh ra trong `/kaggle/working`. Dùng một shop root riêng cho mỗi câu. Kiểm tra đường dẫn mà các tool đọc file resolve nằm trong shop root. Agent nhận gói dữ liệu tương ứng và rulebook. Với code Python do model sinh, dùng input inference luôn tách khỏi reference và log chứa đáp án. Attach reference ở phiên chấm riêng nếu hai tiến trình cùng nhìn thấy filesystem của notebook.
- Ưu tiên đóng gói sẵn dependency OpenCode dùng để khám phá custom tools trong bước setup. Local đã có khoảng 85 giây chờ npm thử truy cập registry. Kiểm tra tool discovery trước khi đo và ghi riêng thời gian setup, thời gian nạp model và thời gian giải câu. Ghi rõ cấu hình Internet của lượt chạy. Inference chạy qua Ollama trong notebook.

[Launcher Windows để đối chiếu](../tmp/run_opencode_sandbox.py) · [Kaggle T4 ×2](https://www.kaggle.com/product-announcements/735239) · [OpenCode Custom Tools](https://opencode.ai/v1/docs/custom-tools/)

## 2. Tool và prompt

Tái sử dụng `bridge.py`, `run.js`, `tools/inspect_table.js`, `tools/aggregate.js` trong `tmp/opencode-structured/`. Thư mục `src/` bên trong là snapshot helper của Khanh Linh tại `efee164a857736181f9dcd0ebf023f47b11e8844`. Snapshot hoặc source tree Kaggle cần giữ đường import `src.agent.sandbox` và các module phụ thuộc của cùng commit. Trỏ JS bridge và Python data root tới đường dẫn Linux thực tế. Có thể parametr hóa root và đường dẫn bridge trong script dùng chung. [Tool bridge](../tmp/opencode-structured/bridge.py) · [Context và nguồn mang theo](ORNITH_OPENCODE_CONTEXT.md#hợp-đồng-chấm-và-các-file-cần-mang-theo)

- **Cung cấp trọn bộ tool với notebook.** `read` có sẵn trong OpenCode. Các custom tool cần file khai báo JS, `run.js`, `bridge.py`, snapshot `src/` và các thư viện Python thực tế. Đưa nguồn vào gói Kaggle Input hoặc repo bundle mà notebook đọc được. Trong preflight, báo rõ file hoặc dependency nào đang thiếu vì `tmp/` trên máy local bị Git ignore.
- **Chế độ đối chứng local.** Tái lập allowlist `read`, `inspect_table` và `aggregate` của `--structured-tools --question-only`. `inspect_table(null, null)` tìm CSV. `inspect_table(file, column)` đọc nhãn thực tế. `aggregate` nhận `file`, `operation=count_distinct`, `date_column`, `date_expression`, `as_of_date`, `column`, `status_column` và `exclude_values`.
- **Chế độ eval agent.** Cấp thêm `run_python(code)` để Ornith tự viết và chạy Python khi cần. Đây là cấu hình chính để đo khả năng giải bài ngoài `count_distinct`. Bọc `run_python_in_sandbox` của snapshot ở trên trong custom tool OpenCode. Model truyền `code`, runner truyền `business_dir`, `as_of_date`, rulebook, calendar nếu có và thư mục làm việc riêng dưới `/kaggle/working`. Dùng protocol `emit_obs` và `emit_final` của runner. Trả `parsed_output` hoặc chẩn đoán lỗi cho model để nó sửa và gọi lại. Log code, stdout, stderr, trạng thái timeout và kết quả parse. [Python runner trong snapshot](../tmp/opencode-structured/src/agent/sandbox.py#L2122)
- Cả hai chế độ dùng prompt ngắn. `user_prompt = question + "\n\nas_of_date: " + as_of_date`, lấy nguyên văn từ `questions.jsonl`. Full rulebook của **split hiện tại** nằm trong system instructions. README và schema được lấy qua tool.
- Giữ ngữ nghĩa của tool. Ornith chọn tham số theo câu hỏi, README và rulebook. Python resolve khoảng ngày, kiểm tra nhãn, lọc dòng và đếm mã duy nhất. Smoke test dùng cùng output và thông báo lỗi để kiểm tra model có thể tự sửa tham số.
- Chế độ nạp tự động README/schema có thể dùng làm đối chứng nếu cần, với tên chế độ riêng trong manifest. Lượt `biz_101` và `biz_110` đã xác minh trước đây thuộc chế độ đó. Smoke ưu tiên `biz_125` để khớp baseline prompt ngắn.

Đoạn dưới đây là system instructions bổ sung của nhánh `--question-only`, đặt cùng full rulebook và system mặc định của OpenCode.

```text
Tuân thủ rulebook của split và dùng as_of_date từ đầu vào. Dùng inspect_table để xác nhận cột và nhãn thực tế dùng khi lọc. Dùng aggregate để tính dựa trên các cột, ngày và quy tắc vừa xác định. Trả đúng một JSON có hai trường type và answer từ kết quả tool. Nếu chưa xác minh được, trả {"type":"abstain","answer":null}. Dữ liệu nằm trong /data. Đọc /data/README.md để hiểu quy ước của shop. Gọi inspect_table với file và column đều là null để tìm bảng, rồi đọc nhãn từ cột trạng thái.
```

Trong Kaggle, thay `/data` ở đoạn hướng dẫn bằng shop root mà agent thực sự nhìn thấy. Ở chế độ eval agent, bổ sung hướng dẫn cho phép model tự viết Python qua `run_python`, dùng `emit_obs` khi cần quan sát và gọi `emit_final(answer, type=...)` với kiểu tường minh khi đã có kết quả. Ghi đúng user prompt và system inputs thực tế ra trace.

## 3. Cấu hình và thứ tự các cell

1. **Config và preflight.** Đặt đường dẫn Kaggle Inputs, thư mục output, ID câu smoke, mode, temperature và số worker ở đầu notebook. Xác minh hai thiết bị bằng `nvidia-smi -L`. Kiểm tra repo, model bundle, `questions.jsonl`, `rulebook.md`, package của shop và scorer. Có chế độ chấm khi split có reference. Kiểm tra quyền đọc input và quyền ghi output.
2. **Setup runtime.** Nạp binary và dependency đã pin, khởi động Ollama, đợi endpoint sẵn sàng. Nạp model với `num_ctx=16384`, `seed=42`, `num_batch=128`, `presence_penalty=0`, `temperature=0` cho baseline. Đặt giới hạn OpenCode context 16.384, output 2.048, tối đa 6 lượt và tắt auto-compaction. Xác minh các tool được OpenCode cấp và gọi được theo chế độ. Kiểm tra `read` trả README, `inspect_table` trả schema hoặc nhãn, `aggregate` trả object kết quả và `run_python` thực thi được code truyền vào. Lưu phiên bản runtime, Python, pandas và NumPy thực tế để giải thích khác biệt với local.
3. **Smoke bằng một T4 trước.** Chạy một câu mỗi lần. Sau khi nạp model, ghi `ollama ps` và `nvidia-smi` để biết context thực chạy, tỷ lệ CPU/GPU và VRAM. Nếu cần hai card để chứa model, ghi đúng cách phân bổ. Nếu một card chạy ổn cả 16K, thử tùy chọn hai worker cho batch trên hai GPU riêng. Mỗi worker cần port Ollama và thư mục phiên OpenCode riêng. Đo throughput thực tế trước khi dùng hai worker làm mặc định.
4. **Chạy smoke end-to-end.** Tái lập đối chứng bằng `q_5c19a3193881` của `biz_125` ở temp 0. User prompt là `Tính riêng ngày hôm nay, cửa hàng bán được bao nhiêu đơn hàng?\n\nas_of_date: 2025-03-28`. Số **41** chỉ dùng ở kiểm tra sau inference. Thêm một câu CSV có phép tính ngoài `aggregate` cho chế độ eval agent. Trace của ca này phải cho thấy Ornith sinh code, gọi `run_python`, nhận kết quả và chốt đáp án. Nếu một ca lệch, xác định nó lệch ở khám phá dữ liệu, tham số, thực thi hay chốt đáp án.
5. **Eval theo manifest.** Sau smoke, chạy trên các shop holdout nếu đã có manifest theo shop. Cố định danh sách ID, chế độ tool và config trước khi chạy. Khi so sánh temp 0 và 0.4, dùng cùng danh sách và chế độ tool. Lọc reference đúng theo các ID đã chọn trước khi đưa vào scorer để mẫu số PA khớp với run. Ghi rõ phạm vi dữ liệu, phép tính và lý do abstain. Nếu split thiếu đáp án, xuất prediction và trace để kiểm tra, ghi rõ PA chưa tính được.

## 4. Chấm đúng câu trả lời cuối

Tách `raw_final_text` và tool observations trong mỗi record. Dùng `messageID` của phản hồi cuối của OpenCode để ghép các event `text` thuộc đúng phản hồi đó. Lưu cả event hợp lệ, lỗi API và exit status. Bảng dưới ghi cách chuẩn hóa từng dạng final.

| Câu trả lời cuối | Prediction đưa vào scorer |
| --- | --- |
| `{"type":"number","answer":41}` | `{"id":"q_5c19a3193881","type":"number","answer":41}` |
| `41` hoặc `{"answer":41}`, có kết quả `aggregate` đã xác thực cùng câu là `{"type":"number","answer":41}` | Điền `type` từ tool và giữ đáp án model đã chốt. Xuất cùng record kiểu `number` ở trên |
| Có giá trị nhưng thiếu `type`, khớp với payload `final` hợp lệ từ `run_python` trong cùng câu | Điền `type` từ payload `final`, qua kiểm tra schema rồi mới xuất |
| Có giá trị nhưng kiểu còn mơ hồ, hoặc final trống hay không parse được | Record `abstain` với ID và lý do trong trace |

Lấy kiểu từ kết quả thành công của phép tính khớp với giá trị Ornith đã chốt. Với `run_python`, dùng payload đã được runner xác thực có `kind=final`. Ghi `type_source` vào trace để biết kiểu đến từ model hay từ tool. Khóa prediction trước khi load reference. Một giá trị thuần như `12.5` có thể mang kiểu `number` hoặc `percent`, nên nguồn kiểu phải có căn cứ.

Giữ tool result làm bằng chứng riêng. Ca local temp 0.4 có `aggregate.answer=41` và final trống phải chấm baseline là `abstain`. Nếu sau này thử lấy kết quả tool để cứu final, đo lượt đó dưới policy riêng và giữ cả hai trường để so sánh. Dùng `src/eval/scorer.py` hoặc `scripts/evaluate_local.py`. PA là `(correct - wrong) / N`. Submission và prediction dùng `id`, `type`, `answer` theo schema chính thức. [Định dạng dataset](data.md#51-file-kết-quả-submissionjsonl) · [Quy tắc chấm](evaluation.md) · [Scorer](../src/eval/scorer.py)

## 5. Đầu ra bàn giao

- Notebook có thể chạy từ trên xuống sau khi attach đủ Kaggle Inputs. Cell đầu nêu chính xác input nào bắt buộc và cách tìm đường dẫn model, repo, dữ liệu.
- Trong một thư mục run ở `/kaggle/working`, lưu manifest có phiên bản, digest nguồn, split và ID câu, context, seed, temp, policy chấm, số worker và phân bổ GPU. Lưu `predictions.jsonl`, trace theo ID và báo cáo metric. Ghi kết quả theo từng câu để giữ tiến độ nếu phiên dừng.
- Trace mỗi câu giữ input, tool name, args, output hoặc lỗi, raw final, prediction đã normalize, `type_source`, finish reason, thời gian và token nếu có. Có thể lưu đường dẫn và hash rulebook cùng một bản nội dung theo run để tránh lặp toàn văn ở mỗi câu.
- Báo cáo ghi số câu, đúng, sai, abstain, PA, thời gian và số ca tool tính xong nhưng final trống. Ghi riêng kết quả đối chứng CSV `count_distinct` và chế độ có `run_python`. Ghi XLSX, SQLite và các phép tính khác theo phạm vi loader và runtime thực sự đã kiểm tra. Đóng gói Docker nộp BTC là công việc riêng.

Handoff hoàn thành khi notebook có preflight rõ, có thể chạy smoke end-to-end bằng OpenCode và Ornith, xuất prediction đúng schema, và cho phép truy lại từng bước từ câu hỏi đến điểm. Báo rõ trạng thái kiểm chứng Kaggle nếu tại thời điểm bàn giao mới chạy được kiểm tra local.
