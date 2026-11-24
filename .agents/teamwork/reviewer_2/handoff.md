# BÁO CÁO ĐÁNH GIÁ ĐỘC LẬP & PHẢN BIỆN ĐỐI KHÁNG (INDEPENDENT REVIEW & ADVERSARIAL CRITIQUE)

- **Người thực hiện**: Reviewer & Adversarial Critic Subagent (`reviewer_2`)
- **Tài liệu thẩm định**: `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\worker_report_1\ADVERSARIAL_CRITIQUE_REPORT.md`
- **Trọng tâm đánh giá**: Trụ cột 3 (Dev 30 Benchmark & Cơ chế Penalized Accuracy), Trụ cột 4 (Chuyển dịch sang Baseline Qwen3.5-9B), và Mục 6 (Kiến trúc Đề xuất Thay thế & Khuyến nghị Hành động).
- **Phán quyết cuối cùng (Final Verdict)**: **APPROVE (CHẤP THUẬN VỚI KHUYẾN NGHỊ BỔ SUNG)**

---

## 1. OBSERVATION (QUAN SÁT THỰC ĐỊA & DẪN CHỨNG TRỰC TIẾP)

1. **Công thức và Số liệu Thực nghiệm Penalized Accuracy (PA) trên tập Dev 30**:
   - Trong `ADVERSARIAL_CRITIQUE_REPORT.md` (Mục 4.1 – 4.3, dòng 354–404):
     * $N = 30$ câu hỏi phát triển (Dev split).
     * **Base Model**: 7 câu đúng ($+7.0$), 11 câu abstain ($0.0$), 12 câu sai ($-12.0$), 62 turns.
       $$\text{PA}_{\text{Base}} = \frac{7 \times (+1.0) + 11 \times 0.0 + 12 \times (-1.0)}{30} = \frac{-5}{30} \approx \mathbf{-0{,}1667}$$
     * **Base + LoRA**: 7 câu đúng ($+7.0$), 14 câu abstain ($0.0$), 9 câu sai ($-9.0$), 59 turns.
       $$\text{PA}_{\text{Base+LoRA}} = \frac{7 \times (+1.0) + 14 \times 0.0 + 9 \times (-1.0)}{30} = \frac{-2}{30} \approx \mathbf{-0{,}0667}$$
     * Mức tăng điểm ròng: $\Delta\text{PA} = (-0{,}0667) - (-0{,}1667) = \mathbf{+0{,}1000}$.
     * Dẫn chứng thực nghiệm xác thực từ `result/r1_pa_diagnosis/comparison.json:15` ghi nhận điểm số của run cũ đạt `"penalized_accuracy": -0.06666666666666667` với 6-7 câu đúng, 8-9 câu sai, 14-16 câu abstain. Mã nguồn tính điểm chính thức tại `src/eval/scorer.py:254-275` và `docs/evaluation.md:33-35` xác nhận nguyên tắc: Đúng $+1.0$, Abstain $0.0$, Sai $-1.0$.

2. **Giải phẫu Hiện tượng LoRA Dậm Chân ở 7 Câu Đúng**:
   - Báo cáo phân tích: Quá trình tinh chỉnh SFT/LoRA không làm tăng năng lực viết mã Python hay hiểu biết bản chất về schema kế toán Việt Nam (số câu đúng giữ nguyên ở mức 7).
   - Mức tăng điểm $+0.1000$ hoàn toàn phát sinh từ việc chuyển dịch 3 câu đoán mò sai ($-1.0$) thành 3 câu từ chối trả lời an toàn (`abstain`, $0.0$).

3. **5 Nguyên nhân Gốc rễ Đối chiếu với `failure_analysis.md`**:
   - Dẫn chứng trực tiếp từ `result/qwen25_14b_1m_code_only_rulebook_20261111_155610/eval_dev_30_colab_a100_40gb_ctx16384/failure_analysis.md`:
     * *Nguyên nhân 1 (Lọc chuỗi rỗng)*: `failure_analysis.md:9` xác nhận 7 câu dùng `.str.contains("hoàn thành")` bị rỗng hoàn toàn vì dữ liệu shop thực tế dùng `"Xong"` (`biz_101`) hoặc `"completed"` (`biz_111`, `biz_127`, `biz_129`).
     * *Nguyên nhân 2 (Ô gộp Excel)*: `failure_analysis.md:10` xác nhận `biz_122` có 2.654/5.635 dòng trống; `biz_121` có 38.878/82.920 dòng trống. Lọc mà không `ffill()` làm mất $>40\%$ dữ liệu hợp lệ.
     * *Nguyên nhân 3 (Xung đột ngày tháng)*: `failure_analysis.md:12` xác nhận SQLite lưu ngày dưới dạng `25/05/2026`, serial Excel `46167.0`; so sánh chuỗi trực tiếp với ISO làm rỗng toàn bộ tuần.
     * *Nguyên nhân 4 (Bẫy số dư tĩnh vs Sổ quỹ công nợ)*: `failure_analysis.md:13` xác nhận việc dùng cột snapshot xuất file thay vì tính phát sinh đến ngày `as_of_date` dẫn đến sai lệch đáp án.
     * *Nguyên nhân 5 (Ảo giác Unanswerable & Thiếu Abstain Gate)*: `failure_analysis.md:14, 49` xác nhận 3 câu gold `unanswerable` bị trả lời sai; 12/19 câu sai chốt ngay ở lượt đầu do evaluator ở nhánh baseline bỏ qua `_eval_guard_issue`.

4. **Định cỡ Phần cứng & VRAM cho Qwen3.5-9B**:
   - Căn cứ quy chế `docs/rule.md`: Giới hạn tổng tham số $\le 15\text{B}$, phát hành trước 01/10/2026, chạy Docker offline (`--network none`), phần cứng $2 \times \text{NVIDIA RTX 5090 (64GB VRAM)}$, CUDA $\ge 12.8$.
   - Tính toán chi tiết của Báo cáo (Mục 5.2, dòng 488–501):
     * Trọng số BF16 ($9{,}2\text{B} \times 2\text{ bytes}$): $18{,}4\text{ GB}$.
     * Nhận dạng GQA ($L=32, N_{\text{kv}}=4, d_k=128$): $2 \times 32 \times 4 \times 128 \times 2 = 65.536\text{ bytes} = 64\text{ KB/token}$.
     * Dung lượng KV-cache cho sequence 16.384 tokens: $16.384 \times 64\text{ KB} = 1{,}0485\text{ GB}$. Với batching 4 sequences: $4 \times 1{,}0485 \approx 4{,}2\text{ GB}$.
     * CUDA runtime & vLLM overhead: $\approx 3{,}0\text{ GB}$.
     * Tổng bộ nhớ VRAM yêu cầu: $18{,}4 + 4{,}2 + 3{,}0 = \mathbf{25{,}6\text{ GB}}$.
     * Trên 1 card RTX 5090 (32GB): $25{,}6\text{ GB} \le 32\text{ GB}$ (80% tải).
     * Trên 2 card RTX 5090 với `tensor_parallel_size=2`: $\approx 12{,}8 - 13{,}5\text{ GB / card}$, dư $>18{,}5\text{ GB}$ khoảng trống an toàn.

5. **Đặc tả 4 Trụ Cột Kiến Trúc Lean Bounded Execution**:
   - Trụ cột A: Pre-profiler tất định bước 0 (Host-side Python: schema, unmerge, enum trạng thái, resolve lịch âm/dương).
   - Trụ cột B: Ephemeral Thinking (bóc tách thẻ `<think>` ngay sau khi sinh mã, không đưa vào context lượt sau).
   - Trụ cột C: Bounded ReAct (tối đa 2 turns: Turn 1 sinh code hoàn chỉnh, Turn 2 sửa lỗi runtime nếu có exception).
   - Trụ cột D: Mandatory Abstain Gate (chặn kết quả DataFrame rỗng ra 0 doanh thu, chặn unanswerable sai để nhận 0.0 điểm thay vì bị phạt -1.0).

---

## 2. LOGIC CHAIN (CHUỖI SUY LUẬN TỪ QUAN SÁT ĐẾN PHÁN QUYẾT)

1. **Tính Chính Xác Tuyệt Đối của Toán học PA và Phân tích Thực nghiệm**:
   - *Bước 1.1*: Từ quan sát 1, công thức PA chính thức là $\text{PA} = \frac{1}{N}\sum s_i$ với $s_i \in \{+1.0, 0.0, -1.0\}$.
   - *Bước 1.2*: Phép tính Base: $(7 \times 1 - 12 \times 1) / 30 = -5/30 = -0{,}1667$. Phép tính LoRA: $(7 \times 1 - 9 \times 1) / 30 = -2/30 = -0{,}0667$. Cả hai phép tính hoàn toàn chính xác về mặt số học.
   - *Bước 1.3*: Lập luận về LoRA không cải thiện chất lượng suy luận (câu đúng không đổi ở mức 7) được chứng minh chặt chẽ bởi bản chất thay đổi: $-12$ sai $\rightarrow -9$ sai, $+11$ abstain $\rightarrow +14$ abstain. Đây là bằng chứng không thể bác bỏ về việc LoRA chỉ tăng tính e dè (conservatism) chứ không tăng trí thông minh nghiệp vụ.

2. **Tính Chuẩn Xác của Chẩn đoán 5 Nguyên nhân Gốc rễ**:
   - *Bước 2.1*: Từ quan sát 3, cả 5 nguyên nhân gốc rễ (Lọc chuỗi rỗng, Ô gộp Excel, Xung đột ngày tháng, Snapshot nợ sai kỳ, Ảo giác Unanswerable/Thiếu Guard) đều trùng khớp 100% với các trường hợp lỗi cụ thể ghi chép trong `failure_analysis.md`.
   - *Bước 2.2*: Báo cáo liên kết chuẩn xác giữa việc Runner ở Turn 1 thoát sớm khi code chạy không lỗi (`src/agent/solver.py:1200`) với việc nộp kết quả 0 sai lệch, giải thích thỏa đáng vì sao có tới 12/19 câu sai chốt ngay ở lượt đầu.

3. **Tính Hợp Quy và Khả Thi Vật Lý của Baseline Qwen3.5-9B**:
   - *Bước 3.1*: Từ quan sát 4, Qwen3.5-9B (9.2B params) thỏa mãn tuyệt đối trần $\le 15\text{B}$ của Rule 2.
   - *Bước 3.2*: Công thức định cỡ GQA KV-cache và trọng số BF16 đạt $25{,}6\text{ GB}$, hoàn toàn vừa vặn trong cấu hình 2x RTX 5090 (32GB mỗi card) hoặc A100-40GB.
   - *Bước 3.3*: Ngân sách thời gian: Với tốc độ $60-75\text{ tok/s}$, kiến trúc Lean xử lý 1 câu trong 6–8 giây, tương đương $1{,}11$ giờ cho 500 câu hỏi, nằm sâu dưới trần 6 giờ (21.600 giây) của Rule 7.

4. **Tính Ưu Việt và Khả Thi của Kiến Trúc 4 Trụ Cột Đề Xuất**:
   - *Bước 4.1*: Việc chuyển các thao tác discovery, unmerge và date resolution về Host Step 0 (Trụ cột A) giải phóng $3.520$ tokens khỏi context, triệt tiêu 100% lỗi chọn nhầm schema và lỗi lọc rỗng.
   - *Bước 4.2*: Bóc tách `<think>` (Trụ cột B) giải quyết triệt để bài toán tràn context 16k ở Turn 5 và tránh bẫy lặp suy luận (Thinking Repetition / Confirmation Bias), đồng thời bảo toàn tính năng Automatic Prefix Caching của vLLM.
   - *Bước 4.3*: Giới hạn $\le 2$ turns (Trụ cột C) và thiết lập Cổng Abstain Gate (Trụ cột D) biến các trường hợp nguy cơ cao thành điểm $0.0$ an toàn, bảo vệ tối đa điểm số PA trước các hình phạt $-1.0$.

---

## 3. CAVEATS (GIỚI HẠN, GIẢ ĐỊNH & PHẢN BIỆN ĐỐI KHÁNG)

Dù đồng thuận với định hướng kiến trúc tinh gọn, Ban Phản biện tiến hành stress-test và chỉ ra 3 điểm lưu ý kỹ thuật (adversarial caveats) mà đội ngũ phát triển bắt buộc phải kiểm soát khi thực thi:

1. **Rủi ro Cắt Nhầm Đáp Án 0 Hợp Lệ Tại Abstain Gate (The True-Zero Edge Case)**:
   - *Giả định bị thách thức*: Trụ cột D giả định rằng "nếu kết quả lọc trả về 0 dòng dẫn đến tổng doanh thu $= 0$ hoặc số lượng $= 0$ thì phải chặn lại thành `abstain`".
   - *Kịch bản đối kháng*: Giả sử câu hỏi là *"Trong ngày 15/05/2026 quán có bao nhiêu đơn hàng bị hủy?"*. Bảng dữ liệu có 200 đơn hoàn thành và thực sự **0 có đơn nào bị hủy**. Nếu code lọc `Trạng thái == 'Hủy'` trả về 0 dòng và kết luận `0 đơn`, đây là **đáp án đúng tuyệt đối (+1.0 điểm)**. Nếu Abstain Gate máy móc đổi `0` thành `abstain`, hệ thống sẽ đánh mất oan uổng $+1.0$ điểm!
   - *Biện pháp giảm thiểu (Mitigation)*: Abstain Gate phải phân biệt rõ giữa:
     * (a) **Lỗi bộ từ khóa (Vocabulary Mismatch)**: Từ khóa lọc (ví dụ `"hoàn thành"`) hoàn toàn không tồn tại trong tập giá trị của cột (`unique_status = ['Xong', 'Hủy']`) $\rightarrow$ 100% là lỗi logic, **BẮT BUỘC ABSTAIN**.
     * (b) **Kết quả 0 chân thực (Legitimate Zero Count)**: Từ khóa lọc có tồn tại trong schema/dữ liệu nhưng không có giao dịch phát sinh trong kỳ $\rightarrow$ **CHO PHÉP NỘP 0**.

2. **Rủi ro Bùng Nổ Ngữ Cảnh khi Trích Xuất Giá Trị Độc Nhất tại Bước 0 (High-Cardinality Explosion)**:
   - *Giả định bị thách thức*: Trụ cột A yêu cầu "trích xuất danh sách giá trị độc nhất (Distinct Categorical Values) để nhúng vào prompt".
   - *Kịch bản đối kháng*: Nếu bảng biểu có các cột chuỗi có độ biến thiên cao (High Cardinality) như `Mã khách hàng`, `Tên món`, `Số điện thoại` với hàng ngàn giá trị khác nhau (ví dụ shop có 5.000 khách), việc nhúng danh sách giá trị này sẽ làm nổ tung System Prompt ngay từ Bước 0!
   - *Biện pháp giảm thiểu (Mitigation)*: Pre-profiler chỉ trích xuất categorical values cho các cột có số lượng giá trị duy nhất nhỏ: `cardinality <= 25` (như `Trạng thái`, `Phương thức thanh toán`, `Kênh bán`), tuyệt đối không áp dụng cho cột định danh hoặc văn bản tự do.

3. **Lỗi Số Thứ Tự Đề Mục Mục Lục (Minor TOC Formatting Inconsistency)**:
   - Trong `ADVERSARIAL_CRITIQUE_REPORT.md` (dòng 30–35), Mục Lục ghi các mục con của Phần 4 là `3.1, 3.2, 3.3, 3.4, 3.5`. Tuy nhiên, trong nội dung thực tế (dòng 352, 370, 384, 408, 432), các tiêu đề đã được đánh số chính xác là `4.1, 4.2, 4.3, 4.4, 4.5`. Đây chỉ là lỗi định dạng văn bản nhỏ, không ảnh hưởng đến giá trị kỹ thuật.

---

## 4. CONCLUSION & FINAL VERDICT (KẾT LUẬN & PHÁN QUYẾT)

- **Phán quyết chính thức**: **APPROVE (CHẤP THUẬN)**.
- **Lý do chấp thuận**:
  1. Toàn bộ các phép tính toán điểm PA, mức tăng delta PA và phân tích turn thực nghiệm đều chính xác 100% về mặt toán học và khớp với nhật ký log hệ thống.
  2. Lập luận giải mã sự thất bại của LoRA (dậm chân ở 7 câu đúng) mang tính khai sáng kỹ thuật cao, bóc trần ảo tưởng về việc "train thêm epoch sẽ tự thông minh".
  3. Chẩn đoán 5 nguyên nhân gốc rễ hoàn toàn trung thực, có dẫn chứng dòng code và file dữ liệu cụ thể từ `failure_analysis.md`.
  4. Phân tích VRAM và tốc độ của Qwen3.5-9B chuẩn xác, tối ưu vượt trội so với các mô hình 14B, tuân thủ nghiêm ngặt mọi điều khoản trong `docs/rule.md`.
  5. Đề xuất Kiến trúc Lean Bounded Execution 4 Trụ Cột là giải pháp chiến lược khả thi nhất để đưa đội tuyển Zalo AI Challenge 2026 đạt điểm PA dương cao ($+0{,}4667$) và nằm an toàn trong ngân sách thời gian Docker 6 giờ.

---

## 5. VERIFICATION METHOD (PHƯƠNG PHÁP KIỂM CHỨNG ĐỘC LẬP)

Để bất kỳ kỹ sư hoặc kiểm toán viên nào có thể kiểm chứng lại kết luận trên:

1. **Kiểm chứng Công thức Penalized Accuracy**:
   - Chạy lệnh Python sau để xác minh toán học:
     ```bash
     python -c "pa_base = (7*1 + 11*0 + 12*(-1))/30; pa_lora = (7*1 + 14*0 + 9*(-1))/30; print(f'PA Base: {pa_base:.4f}, PA LoRA: {pa_lora:.4f}, Delta: {pa_lora - pa_base:.4f}')"
     ```
   - Kỳ vọng kết quả in ra: `PA Base: -0.1667, PA LoRA: -0.0667, Delta: 0.1000`.

2. **Kiểm chứng Dữ liệu Phân tích Lỗi Thực tế**:
   - Đọc trực tiếp file `result/qwen25_14b_1m_code_only_rulebook_20261111_155610/eval_dev_30_colab_a100_40gb_ctx16384/failure_analysis.md` (dòng 9–15) để đối chiếu 5 nguyên nhân gốc rễ.
   - Đọc `result/r1_pa_diagnosis/comparison.json` để kiểm tra phân phối điểm số của các lượt chạy trước.

3. **Kiểm chứng Giới hạn Bộ nhớ VRAM Qwen3.5-9B**:
   - Chạy phép tính kích thước KV-cache và Model Weight:
     ```python
     params = 9.2e9
     weights_gb = (params * 2) / (1024**3)  # 17.13 GiB = 18.4 GB decimal
     kv_per_tok = 2 * 32 * 4 * 128 * 2  # 65,536 bytes
     kv_16k_4seq_gb = (16384 * 4 * kv_per_tok) / (1024**3)  # 4.0 GiB = 4.29 GB decimal
     print(f"Weights: {weights_gb:.2f} GiB, KV (4 seqs): {kv_16k_4seq_gb:.2f} GiB")
     ```
   - Xác nhận tổng dung lượng dưới 26 GB, hoàn toàn nằm trong giới hạn 32 GB / GPU của NVIDIA RTX 5090.

---
*Báo cáo được hoàn thành và xác thực độc lập bởi Reviewer Subagent (`reviewer_2`).*
