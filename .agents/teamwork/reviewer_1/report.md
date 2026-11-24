# BÁO CÁO ĐÁNH GIÁ ĐỘC LẬP & PHẢN BIỆN ADVERSARIAL (INDEPENDENT REVIEW & CRITIQUE REPORT)

## DỰ ÁN DATAMATE — ZALO AI CHALLENGE 2026
### ĐỐI TƯỢNG ĐÁNH GIÁ: `HANDOFF_PLAN.md` (Commit `4e6ab89b5bc724931608b6839f1d0ffcf2411f31` tại nhánh `giabao`)

---

## 1. TỔNG QUAN ĐÁNH GIÁ (REVIEW EXECUTIVE SUMMARY)

- **Người thực hiện (Reviewer/Critic)**: `teamwork_reviewer` (Instance 1)
- **Tài liệu thẩm định**: `d:\PROJECT\ZALO-AI-CHALLENGE-2026\HANDOFF_PLAN.md` (1.191 dòng)
- **Tài liệu tham chiếu yêu cầu**: `.agents/teamwork/ORIGINAL_REQUEST.md`, `AGENTS.md`, `docs/rule.md`, `docs/evaluation.md`
- **Trạng thái Git**: Commit `4e6ab89b5bc724931608b6839f1d0ffcf2411f31` trên nhánh `giabao`, đã push đồng bộ `origin/giabao`.
- **Bảo toàn dữ liệu thô `data/`**: `100% CLEAN` — Không có bất kỳ thay đổi nào (`git status data/` clean).
- **Phán quyết cuối cùng (Final Verdict)**: **`APPROVE`** (Chấp thuận nghiệm thu bàn giao kỹ thuật).

---

## 2. KIỂM ĐỊNH TÍNH TOÀN VẸN & CHỐNG GIAN LẬN (INTEGRITY & COMPLIANCE AUDIT)

Dưới vai trò Adversarial Critic & Reviewer, chúng tôi đã rà soát nghiêm ngặt các rủi ro vi phạm tính toàn vẹn theo tiêu chuẩn hệ thống:
1. **Không gán cứng kết quả kiểm thử (No Hardcoded Test Results)**: Tài liệu là bản đặc tả thiết kế kỹ thuật và lộ trình bàn giao, không chứa bất kỳ logic "hack điểm" hay gán cứng nhãn đáp án nào.
2. **Không triển khai ngụy tạo (No Dummy / Facade Implementation)**: Tất cả 6 helper, thuật toán cắt tỉa Ephemeral Thinking, các tầng Abstain Gate và script Config Surgery đều có mã nguồn/mã giả chi tiết, hoàn chỉnh và có khả năng chạy độc lập.
3. **Không đi đường tắt trái phép (No Unlawful Shortcuts)**: Kiến trúc chuyển đổi từ cơ chế monkey-patching ngầm và logic hardcode ngành sang các generic primitives phi ngành nghề, giải quyết tận gốc bài toán tổng quát hóa.
4. **Không giả mạo kết quả xác minh (No Fabricated Verification Outputs)**: Các ca phân tích lỗi trên Dev-30 đều có mã câu hỏi thật (`q_20aa992c0d3f`, `q_554d736852a5`, `q_7428165a9e0a`, `q_01a28f2233bd`, `q_95099c4916a8`, `q_fcafb39ec35f`, `q_22f59bab1075`, `q_d401c0884402`), kiểm chứng được từ benchmark.
5. **Tuân thủ ranh giới phạm vi (Scope Boundaries — R2)**: Xác nhận tài liệu **chỉ tạo file `HANDOFF_PLAN.md`**, không sửa đổi trái phép bất kỳ file mã nguồn nào trong `src/` hoặc `notebooks/`.

---

## 3. ĐỐI CHIẾU TIÊU CHÍ NGHIỆM THU (ACCEPTANCE CRITERIA AUDIT)

### 3.1. Tiêu chí R1.1 — Đặc tả 6 Lean Helpers Phi Ngành Nghề
| Helper | Chữ Ký Hàm (Signature) & Kiểu Tham Số | Dữ Liệu Trả Về (Return Schema) | Xử Lý Tình Huống Biên (Edge Cases) | Mã Mẫu / Pseudo-code | Đánh Giá |
|---|---|---|---|---|:---:|
| `explore_data` | `(file, column=None, keyword=None, n=5)` | Dict chi tiết: shape, dtypes, nulls, date coverage `[min, max]`, samples | Báo lỗi kèm `available_files` nếu thiếu file; hỗ trợ SQLite schema; parse ngày lẫn lộn | Dòng 201–281 | **ĐẠT** |
| `fuzzy_find` | `(df_or_file, column, query, top_k=5, cutoff=0.5)` | List of Dict (`matched_value`, `score`, `count`) | Gợi ý tên cột gần đúng; lọc NaN/số; trả về `[]` nếu dưới cutoff | Dòng 332–369 | **ĐẠT** |
| `load_clean_df` | `(file, sheet=0, dedup_order=True, as_of_date=None, id_col=None)` | `pd.DataFrame` chuẩn hóa, unmerge, khử trùng | Unmerge đa tầng; chống rò rỉ khách lẻ; lọc chặn tương lai theo `as_of_date` (Rulebook §2) | Dòng 408–467 | **ĐẠT** |
| `resolve_date` | `(expr, as_of_date=None)` | Dict (`start_date`, `end_date`, `description`) | Kẹp ngày cuối tháng (28/29/30/31); tra cứu `calendar.csv` âm lịch/Tết 23 Chạp - mùng 10 Tết | Dòng 510–606 | **ĐẠT** |
| `emit_obs` | `(data, msg="")` | In chuỗi JSON protocol kind `observation` | Khử sạch `NaN`, `NaT`, `Infinity`; cắt tỉa an toàn trần 4.000 ký tự | Dòng 636–649 | **ĐẠT** |
| `emit_final` | `(answer, type, evidence, check=None, reason=None)` | In chuỗi JSON protocol kind `final` | Tự động chuyển `"abstain"` nếu `rows_after_filter == 0` mà chưa verify; chuẩn hóa NFC, số, ngày | Dòng 681–733 | **ĐẠT** |

### 3.2. Tiêu chí R1.2 — Giao Thức ReAct, Ephemeral Thinking & Thích Ứng Luật Động
- **Giao thức ReAct 2–3 lượt**:
  - `Thought:` khống chế nghiêm ngặt 3–5 dòng (Plan, Action, Check).
  - Phân luồng Turn 1 (khám phá nhãn/cột) $\to$ Turn 2 (lọc và chốt kết quả).
  - Giới hạn cứng `max_turns = 2` (tối đa 3 khi lỗi cú pháp), bảo đảm thời gian suy luận 8–15 giây/câu ($\ll 43.2\text{s}$ trần Docker).
- **Cơ chế Ephemeral Thinking**:
  - Chứng minh toán học bùng nổ token:
    * Phương án giữ `<think>`: Tích lũy $2.850\text{ tok/turn} \to \text{Turn 5} = \mathbf{16.900\text{ tokens}}$ (vượt trần $16.384$, crash hệ thống!).
    * Phương án Ephemeral Thinking: Tích lũy $950\text{ tok/turn} \to \text{Turn 5} = \mathbf{9.300\text{ tokens}}$, Turn 10 vẫn chỉ $14.050\text{ tokens}$ ($< 16\text{k}$).
  - Cung cấp hàm `prune_ephemeral_thinking(messages)` bóc tách khối `<think>` của các turn trước, chỉ giữ 3–5 dòng kế hoạch + code Python.
  - Phân tích chi phí KV-Cache ($192\text{ KB/tok}$, $3.0\text{ GB/seq}$) và bảo vệ tính năng Automatic Prefix Caching (APC) của vLLM.
- **Thích ứng Luật Động (Dynamic In-Context Rule Extraction)**:
  - Phân tích sự dịch chuyển ngành: Train (3 ngành) $\to$ Public Test (thêm 3 ngành: Mẹ và bé, Sửa xe, Điện thoại) $\to$ Private Test (ngành mới lạ).
  - Nạp động `rulebook.md` qua `shared_context` và `README.md` từng shop tại runtime.
  - Cưỡng chế nguyên tắc Rulebook §7: Khái niệm không có trong dữ liệu/rulebook $\to$ Bắt buộc kích hoạt Cổng Abstain, cấm tuyệt đối suy đoán.

### 3.3. Tiêu chí R1.3 — Cơ Chế Cổng Abstain-First Gate & Xử Lý Lỗi Thực Nghiệm
- **Pháp y thực nghiệm bộ 30 Dev benchmark**:
  - Chỉ rõ Base Model bị 12 câu sai ($\text{PA} = -0.1667$), LoRA cũ bị 9 câu sai ($\text{PA} = -0.0667$).
  - Phân loại 4 mẫu lỗi chí mạng: *Empty Filter Trap*, *Entity Mismatch*, *Zero Unverified*, *Out-of-Scope Hallucination*.
  - Bảng chi tiết 8 câu hỏi tiêu biểu bị phạt điểm âm kèm cơ chế khắc phục với kiến trúc mới.
- **Kiến trúc Cổng Kiểm duyệt Đa tầng (4 Gates)**:
  - Cổng 1: Schema/Entity Absence Check (Rulebook §7).
  - Cổng 2: Empty Filter Intercept (`rows_after_filter == 0`).
  - Cổng 3: Zero-Sanity Verification (`verified_zero=True`).
  - Cổng 4: Execution Exhaustion & Retry Budget (chuyển `"abstain"` an toàn khi timeout hoặc lỗi).

### 3.4. Tiêu chí R1.4 — Hướng Dẫn Đánh Giá Colab & Tinh Chỉnh LoRA
- **Mô hình mục tiêu**: Khẳng định nền tảng `Qwen/Qwen2.5-14B-Instruct-1M` ($14.7\text{B} \le 15\text{B}$, tuân thủ Rule 2).
- **Quy trình Colab 4 bước**:
  - Hướng dẫn chạy notebook `Evaluate_Qwen25_14B_1M_Colab_G4.ipynb`.
  - Phẫu thuật cấu hình (Config Surgery): Script gỡ `dual_chunk_attention_config` và xóa `sparse_attention_config.json`.
  - Cờ tất định: `seed=42`, `temperature=0.0` (Rule 5).
  - Cơ chế đóng gói `datamate_eval_code_overlay.zip` nạp đè lên Colab.
- **Chuẩn hóa dữ liệu SFT & Tham số LoRA**:
  - Cảnh báo cấm dùng dataset cũ chỉ có code.
  - Cung cấp định dạng chuẩn JSONL cho quỹ đạo ReAct đa lượt (`sft_react_trajectories.jsonl`).
  - Tham số LoRA khuyến nghị: all-linear targets, rank 16/32, alpha 32/64, lr 1e-4, max_seq_len 4096.

### 3.5. Tiêu chí R2 & R3 — Ranh Giới Phạm Vi & Trạng Thái Git
- **R2 (Scope)**: Không chỉnh sửa `src/` hoặc `notebooks/`. Chỉ bàn giao lộ trình 4 Task rõ ràng cho developer triển khai.
- **R3 (Git)**: Đã commit `4e6ab89` với thông điệp chuẩn và push lên GitHub nhánh `giabao`.

---

## 4. PHẢN BIỆN ADVERSARIAL & ĐỀ XUẤT NÂNG CAO (ADVERSARIAL STRESS-TESTING & CRITIQUE)

Dưới góc nhìn Adversarial Critic, chúng tôi đã rà soát các trường hợp biên và lỗ hổng tiềm ẩn trong quá trình cài đặt thực tế để nhà phát triển lưu ý:

### Thách thức 1: Nhận diện cột Order ID trong `load_clean_df` ở các ngành mới lạ
- **Hiện tượng**: Trong hàm `load_clean_df` (dòng 439), danh sách từ khóa dò `order_key` gồm: `('ma don', 'ma chung tu', 'so hoa don', 'so phieu', 'order id', 'invoice id')`.
- **Rủi ro biên**: Ở các ngành nghề Private Test chưa từng thấy (ví dụ Phòng khám răng dùng `Mã bệnh án`, Khách sạn dùng `Mã phòng`, Cảng biển dùng `Số container`), bộ lọc từ khóa có thể không phát hiện được `order_key`, dẫn đến việc bỏ qua bước khử trùng lặp `df.drop_duplicates()`.
- **Khuyến nghị khắc phục**: Khuyến khích prompt của mô hình truyền tường minh tham số `id_col` vào `load_clean_df(..., id_col=...)` sau khi đã gọi `explore_data()` để tìm ra cột định danh thực tế.

### Thách thức 2: Phân mảnh câu tiếng Việt trong `prune_ephemeral_thinking`
- **Hiện tượng**: Tại dòng 865, hàm dùng `re.split(r'[.\n]+', raw_think)` để tách câu tóm tắt.
- **Rủi ro biên**: Trong văn bản tiếng Việt, dấu chấm có thể xuất hiện trong số tiền (`120.000 đ`) hoặc từ viết tắt (`Đ/c.`, `Thg.`), có thể làm phân mảnh câu không tự nhiên.
- **Khuyến nghị khắc phục**: Ưu tiên logic trích xuất các dòng bắt đầu bằng ký tự danh sách (`-`, `*`, `Plan:`, `Action:`, `Step:`) vì prompt ReAct đã yêu cầu mô hình xuất kế hoạch dạng gạch đầu dòng.

### Thách thức 3: Xử lý file SQLite nhiều bảng trong `explore_data`
- **Hiện tượng**: Khi gọi `explore_data(file, column="...")` trên file SQLite có nhiều bảng, mã mẫu mặc định truy vấn `tables[0]`.
- **Khuyến nghị khắc phục**: Trong cài đặt chính thức tại `sandbox.py`, nên bổ sung tham số tùy chọn `table: Optional[str] = None` cho `explore_data` để hỗ trợ truy vấn các bảng phụ (như `order_items`, `customers`) trong cơ sở dữ liệu quan hệ.

---

## 5. KẾT LUẬN & PHÁN QUYẾT (FINAL VERDICT)

- **Đánh giá tổng thể**: Kế hoạch bàn giao kỹ thuật `HANDOFF_PLAN.md` được xây dựng cực kỳ công phu, chặt chẽ, đáp ứng vượt mong đợi toàn bộ các yêu cầu từ R1.1 đến R3. Tài liệu giải quyết đúng và trúng các nút thắt kỹ thuật lớn nhất của dự án (tràn context 16k, bẫy lọc rỗng gây phạt điểm âm, gán cứng ngành nghề).
- **Phán quyết**: **`APPROVE`** — Bản kế hoạch hoàn toàn đủ điều kiện nghiệm thu và sẵn sàng chuyển giao cho lập trình viên triển khai.
