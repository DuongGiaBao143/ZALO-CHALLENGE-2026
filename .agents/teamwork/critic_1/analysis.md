# BÁO CÁO PHẢN BIỆN KIẾN TRÚC & ĐÁNH GIÁ RỦI RO KỸ THUẬT (R3 & R4)
## Dự án: Zalo AI Challenge 2026 — DataMate
## Đơn vị thực hiện: Teamwork Critic / Reviewer / Specialist Agent
## Ngày lập: 2026-11-11

---

## MỤC LỤC
1. [TỔNG QUAN & TÓM TẮT PHẢN BIỆN (EXECUTIVE SUMMARY)](#1-tổng-quan--tóm-tắt-phản-biện-executive-summary)
2. [R3. PHÂN TÍCH RỦI RO CHUYÊN SÂU, ĐIỂM MÙ VÀ VẤN ĐỀ KỸ THUẬT](#2-r3-phân-tích-rủi-ro-chuyên-sâu-điểm-mù-và-vấn-đề-kỹ-thuật)
   - [2.1. Rủi ro Đa lượt (Multi-turn) & Độ trễ (Latency) trong Docker Offline](#21-rủi-ro-đa-lượt-multi-turn--độ-trễ-latency-trong-docker-offline)
   - [2.2. Penalized Accuracy (PA) & Tính Bắt buộc Toán học của Abstain Gate](#22-penalized-accuracy-pa--tính-bắt-buộc-toán-học-của-abstain-gate)
   - [2.3. Thực tế Dữ liệu Hộ kinh doanh Việt Nam vs Naive Profiling](#23-thực-tế-dữ-liệu-hộ-kinh-doanh-việt-nam-vs-naive-profiling)
   - [2.4. Các Chế độ Lỗi Sinh mã (Code Generation) & Bounded Sandbox](#24-các-chế-độ-lỗi-sinh-mã-code-generation--bounded-sandbox)
   - [2.5. Năm Điểm mù Nghiêm trọng Hoàn toàn Bị Bỏ quên](#25-năm-điểm-mù-nghiêm-trọng-hoàn-toàn-bị-bỏ-quên)
3. [R4. TỔNG KẾT ĐÁNH GIÁ & KHUYẾN NGHỊ ĐIỀU CHỈNH](#3-r4-tổng-kết-đánh-giá--khuyến-nghị-điều-chỉnh)
   - [3.1. Phán quyết Kiến trúc (Architectural Verdict)](#31-phán-quyết-kiến-trúc-architectural-verdict)
   - [3.2. Những điểm CẦN GIỮ LẠI (What to Keep)](#32-những-điểm-cần-giữ-lại-what-to-keep)
   - [3.3. Những điểm CẦN ĐIỀU CHỈNH & BỔ SUNG (What to Adjust / Enhance)](#33-những-điểm-cần-điều-chỉnh--bổ-sung-what-to-adjust--enhance)
   - [3.4. Lộ trình Kỹ thuật Ưu tiên Thực thi (Prioritized Engineering Roadmap)](#34-lộ-trình-kỹ-thuật-ưu-tiên-thực-thi-prioritized-engineering-roadmap)

---

## 1. TỔNG QUAN & TÓM TẮT PHẢN BIỆN (EXECUTIVE SUMMARY)

Đề xuất cải tiến pipeline 3 bước được đưa ra gồm:
1. **Bước 1: Bản đồ dữ liệu gọn** (schema tên file, sheet, cột, kiểu dữ liệu, nhãn cho cột ít giá trị, mẫu cho cột nhiều giá trị).
2. **Bước 2: Lượt khám phá có mục tiêu trước khi trả lời** (sandbox tìm kiếm trên toàn bộ dữ liệu, trả về kết quả liên quan vào context qua luồng observation).
3. **Bước 3: Kiểm tra kết quả đáng nghi trước khi chốt** (kiểm tra khi ra 0, `[]`, hoặc nối bảng không khớp, số dòng trước/sau lọc, nhãn đã dùng).

### Phán quyết Tổng thể:
> **FLAWED AS A RUNTIME LLM MULTI-TURN LOOP, BUT VALUABLE IF CONVERTED INTO A DETERMINISTIC PRE-PROCESSING PIPELINE.**  
> (Khiếm khuyết nghiêm trọng nếu triển khai dưới dạng vòng lặp hội thoại đa lượt do LLM tự sinh mã lúc runtime, nhưng chứa đựng ý tưởng cốt lõi rất giá trị nếu được chuyển hóa thành pipeline tiền xử lý và trích xuất tất định bằng mã nguồn Python tĩnh).

### Bằng chứng thực nghiệm cốt lõi từ `failure_analysis.md` (Run `qwen25_14b_1m_code_only_rulebook_20261111_155610` trên 30 câu dev set):
- **Kết quả đánh giá hiện tại:** 4 đúng, 19 sai, 7 abstain $\rightarrow$ **$\text{PA} = -0.5000$** (Cực kỳ nguy hiểm: điểm số âm sâu do bị phạt -1.0 cho 19 câu sai!).
- **12/19 câu sai chốt ngay lượt đầu tiên:** Model tự tin sinh code sai ngữ nghĩa hoặc sai logic tổng hợp, sandbox chạy thành công trả về JSON hợp lệ, nhưng kết quả sai lệch hoàn toàn so với gold.
- **7 câu lọc trạng thái `.str.contains("hoàn thành")` làm rỗng toàn bộ dữ liệu:** Do `biz_101` dùng nhãn `Xong`, còn `biz_111`, `biz_127`, `biz_129` dùng nhãn `completed`. Model sau đó rơi vào ảo giác (tự gán cứng ngày, chia số vô lý) hoặc chốt `unanswerable` sai.
- **13 câu gặp lỗi Runtime Error:** Trong đó có 3 câu abstain liên tục lặp lại nguyên văn đoạn code bị lỗi cả 3 lượt do LLM 14B không có khả năng tự sửa lỗi pandas phức tạp (hậu tố `_x`, `_y` sau merge, ép kiểu NaN thành int).
- **Ô gộp (merged cells) chiếm tới 47% số dòng:** Sheet tháng 9 của `biz_122` có 2.654/5.635 dòng trống mã đơn, ngày và trạng thái. File của `biz_121` có 38.878/82.920 dòng thiếu 3 trường cấp đơn. Naive profiling sẽ làm gãy toàn bộ phép tính nếu không forward-fill trước.

---

## 2. R3. PHÂN TÍCH RỦI RO CHUYÊN SÂU, ĐIỂM MÙ VÀ VẤN ĐỀ KỸ THUẬT

### 2.1. Rủi ro Đa lượt (Multi-turn) & Độ trễ (Latency) trong Docker Offline

#### Ràng buộc hạ tầng & Thể lệ thi đấu:
- Môi trường: Container Docker hoàn toàn ngoại tuyến (`--network none`).
- Phần cứng thẩm định của BTC: `2 × NVIDIA RTX 5090 (32GB VRAM mỗi card = 64GB VRAM tổng)` và `512 GB RAM`.
- Giới hạn mô hình: Tổng tham số tất cả các mô hình $\le 15\text{B}$.
- Thời gian chạy tối đa: **6 giờ (21.600 giây)** cho toàn bộ tập Private Test (~500 câu hỏi), bao gồm cả thời gian nạp mô hình (`docs/rule.md`, Quy định 7).
- **Quy tắc phân định hòa (Tie-breaker):** `docs/evaluation.md`, Mục 2 quy định rõ: *Trong trường hợp bằng điểm nhau trên BXH cuối cùng, thứ hạng sẽ được phân định ưu tiên theo TỔNG THỜI GIAN SUY LUẬN (total inference time)*.

#### Phân tích Ngân sách Thời gian (Time Budget):
- Ngân sách lý thuyết tối đa: $\frac{21.600\text{ giây}}{500\text{ câu}} \approx 43.2\text{ giây / câu}$.
- Sau khi trừ thời gian nạp trọng số mô hình 14B (~3-5 phút) và tiền xử lý dữ liệu của ~15-20 shop: ngân sách an toàn thực tế là **$\le 35\text{ giây / câu}$**.

#### Tác động Tiêu cực của Vòng lặp Khám phá Đa lượt (Multi-turn Observation Loop):
Khi cho LLM thực hiện vòng lặp:  
$\text{Prompt ban đầu} \rightarrow \text{Sinh code khám phá} \rightarrow \text{Sandbox thực thi} \rightarrow \text{Quan sát} \rightarrow \text{Sinh code tính toán} \rightarrow \text{Sandbox thực thi} \rightarrow \text{Kiểm tra}$:
1. **Thời gian sinh token của LLM:**
   - Qwen2.5-14B trên 2x RTX 5090 đạt tốc độ sinh khoảng 35 - 50 tokens/giây ở batch size nhỏ.
   - Lượt 1 (Code khám phá): Sinh ~250 tokens $\rightarrow$ tốn ~5 - 7 giây.
   - Lượt 2 (Code tính toán chính): Sinh ~450 tokens $\rightarrow$ tốn ~9 - 13 giây.
   - Lượt 3 (Retry / Sửa lỗi nếu có): Sinh ~400 tokens $\rightarrow$ tốn ~8 - 11 giây.
   - Tổng thời gian sinh token thuần túy: $22 - 31\text{ giây}$.
2. **Thời gian I/O và Thực thi Sandbox:**
   - Dữ liệu doanh nghiệp lên tới **300.000 dòng**, nhiều file Excel dung lượng lớn (`.xlsx`). Mở một file Excel lớn bằng `pandas`/`openpyxl` có thể mất từ 3 đến 8 giây.
   - Với 2 lượt thực thi sandbox: $2 \times (3 - 8\text{s}) = 6 - 16\text{ giây}$.
3. **Tổng thời gian tích lũy cho 1 câu hỏi:**
   $$\text{Total Latency} = 25\text{s (LLM)} + 12\text{s (Sandbox)} = 37\text{s} \text{ đến } 55\text{s / câu}$$
   $\rightarrow$ **VƯỢT NGƯỠNG NGÂN SÁCH 35 GIÂY!** Nếu 50% số câu hỏi rơi vào multi-turn 2-3 lượt, hệ thống sẽ **bị ngắt sớm (kill process) khi chạm trần 6 giờ**, khiến hàng trăm câu hỏi chưa kịp chạy bị gán điểm `abstain` (0 điểm) theo Quy định 8, làm sụp đổ toàn bộ thứ hạng! Đồng thời, tổng thời gian suy luận kéo dài sẽ khiến đội thi **thua tuyệt đối ở tiêu chí phụ (tie-breaker)**.

#### KV-Cache Thrashing & Context Bloat trong vLLM:
- **Hiện tượng phân mảnh VRAM:** Trong `src/agent/solver.py`, backend vLLM được cấu hình với `enable_prefix_caching=True`. Kỹ thuật này phát huy hiệu quả tối đa khi prompt có tiền tố chung lớn (System Prompt + Rulebook + Business Schema cố định của shop).
- **Phá vỡ Prefix Caching:** Khi mỗi câu hỏi bước vào multi-turn với các đoạn script khám phá và kết quả observation ngẫu nhiên khác nhau, tiền tố chung bị phá vỡ hoàn toàn sau Lượt 1. KV-cache của từng sequence trong batch bắt đầu phân mảnh, chiếm dụng bộ nhớ VRAM nhanh chóng.
- **Context Bloat:** Rulebook (~2.000 tokens) + User Prompt (~1.500 tokens) + Code Lượt 1 (~400 tokens) + Diagnostic Observation (~1.500 tokens) + Code Lượt 2 (~500 tokens) $\rightarrow$ Context vượt 6.000 - 8.000 tokens. Điều này làm giảm đáng kể throughput của batching (phải hạ `max_num_seqs` xuống 1 hoặc 2), triệt tiêu hoàn toàn sức mạnh tính toán song song của 2x RTX 5090.

---

### 2.2. Penalized Accuracy (PA) & Tính Bắt buộc Toán học của Abstain Gate

#### Công thức Đánh giá của Cuộc thi:
$$\text{PA} = \frac{1}{N} \sum_{i=1}^{N} s_i, \qquad s_i = \begin{cases} +1.0 & \text{khi trả lời ĐÚNG} \\ 0.0 & \text{khi từ chối (abstain)} \\ -1.0 & \text{khi trả lời SAI} \end{cases}$$

#### Cơ sở Toán học của Quyết định Suy luận (Decision Theory):
Gọi $p = P(\text{đáp án sinh ra là ĐÚNG})$.  
Kỳ vọng điểm số khi Agent quyết định đưa ra câu trả lời:
$$E[\text{PA}|\text{Answer}] = p \cdot (+1.0) + (1-p) \cdot (-1.0) = 2p - 1$$
Kỳ vọng điểm số khi Agent chủ động từ chối trả lời:
$$E[\text{PA}|\text{Abstain}] = 0.0$$

Để việc đưa ra câu trả lời có lợi hơn từ chối, ta bắt buộc phải có:
$$E[\text{PA}|\text{Answer}] > E[\text{PA}|\text{Abstain}] \iff 2p - 1 > 0 \iff \mathbf{p > 0.5 \quad (50\%!)}$$

> **Ý nghĩa cốt tử:** Trong các bài toán NLP thông thường (đo bằng Accuracy hay F1-score), việc đoán mò luôn có kỳ vọng $\ge 0$. Nhưng trong Zalo AI Challenge 2026, **nếu độ tin cậy của Agent dưới 50%, hành vi đoán mò sẽ trực tiếp kéo tụt điểm số của toàn đội!**

#### Cái bẫy của Bước 3 trong đề xuất ("The Retry Trap"):
Đề xuất Bước 3 ghi: *"Kiểm tra kết quả đáng nghi trước khi chốt (kiểm tra khi ra 0, [], hoặc nối bảng không khớp, số dòng trước/sau lọc, nhãn đã dùng)"*.  
Nhưng **điều gì sẽ xảy ra tiếp theo khi phát hiện kết quả đáng nghi?**
1. **Nếu yêu cầu LLM retry:**  
   Bản chất của các mô hình LLM là xu hướng "chiều lòng prompt" (instruction-following bias). Khi nhận phản hồi: *"Kết quả ra 0 dòng hoặc rỗng, hãy thử lại"*, model 14B sẽ mặc định rằng điều kiện lọc của nó quá chặt. Nó sẽ:
   - Tự động nới lỏng điều kiện lọc (xóa bỏ điều kiện loại đơn hủy, đơn hoàn).
   - Đổi phép so khớp sang `fillna` bừa bãi.
   - Thậm chí bịa ra một giá trị mặc định để trả lời thay vì để trống!
2. **Bằng chứng đanh thép từ `failure_analysis.md`:**
   - `q_20aa992c0d3f`: Sau khi lọc trạng thái làm rỗng tập dữ liệu, model tự gán cứng ngày `2026-05-01` $\rightarrow$ **SAI (-1.0)**.
   - `q_22f59bab1075`: Câu hỏi về tồn kho thực tế, dữ liệu chỉ có `Tồn lớn nhất = 999.999.999`. Thay vì từ chối, model tự giả định 6 cái/hộp và chia ra `166666666` $\rightarrow$ **SAI (-1.0)**.
   - `q_95099c4916a8`: Cột `Loại hình khách` chỉ có giá trị `Cá nhân`. Model coi đó là nhận diện giới tính nữ, lọc ra 0 dòng và kết luận doanh thu nữ là `0%` $\rightarrow$ **SAI (-1.0)**.
   - `q_fcafb39ec35f`: Tìm địa chỉ tuyến đường trong cột tên khách, ra 2 tập rỗng $(0 = 0)$ rồi kết luận doanh thu 2 đường bằng nhau $\rightarrow$ **SAI (-1.0)**.
   - `q_554d736852a5` & `q_e0aef192cb11`: Lọc sai nhãn `hoàn thành` ra rỗng, model vội vàng chốt `unanswerable`, trong khi đáp án chuẩn là tính được $\rightarrow$ **SAI (-1.0)**!

#### Kết luận về Bước 3:
Khi Step 3 phát hiện kết quả bất thường (0 dòng, rỗng, NaN, join miss), nếu không có cơ chế sửa sai tất định (deterministic fix), việc cho LLM "thử lại tự do" sẽ đẩy xác suất đúng $p$ xuống sâu dưới $0.5$, biến các câu có thể đạt 0 điểm (`abstain`) thành **-1.0 điểm phạt**!  
Do đó, **Bước 3 BẮT BUỘC phải là một CỔNG TỪ CHỐI TẤT ĐỊNH (Hard Deterministic Abstain Gate)**: Khi phát hiện kết quả bất thường không thể phục hồi bằng quy tắc chắc chắn 100%, hệ thống phải **cắt lỗ ngay lập tức bằng `type='abstain'` để bảo toàn 0 điểm**.

---

### 2.3. Thực tế Dữ liệu Hộ kinh doanh Việt Nam vs Naive Profiling

Đề xuất Bước 1 giả định rằng việc trích xuất "Bản đồ dữ liệu gọn" (schema, cột, kiểu dữ liệu) là đủ để model hiểu bảng biểu. Đây là một ảo tưởng kỹ thuật nghiêm trọng đối với dữ liệu thực tế của các doanh nghiệp vừa và nhỏ (SME) tại Việt Nam:

1. **Thảm họa Ô gộp (Merged Cells / Multi-level Formats) trong Excel:**
   - Kế toán hộ kinh doanh Việt Nam thường thiết kế Excel để "in ra nhìn cho đẹp", không phải để máy đọc (tidy data). Thông tin hóa đơn (`Mã đơn`, `Ngày tạo`, `Trạng thái`, `Mã khách hàng`) chỉ được ghi ở dòng đầu tiên của cụm hóa đơn, các dòng chi tiết món hàng phía dưới bị gộp ô hoặc để trống hoàn toàn (`NaN`).
   - `failure_analysis.md` chỉ ra:
     - `biz_122` (sheet tháng 9): **2.654 trên 5.635 dòng (47.1%)** bị trống mã đơn, ngày và trạng thái.
     - `biz_121`: **38.878 trên 82.920 dòng (46.9%)** bị thiếu 3 trường cấp đơn này!
   - Nếu Naive Profiler ở Bước 1 đọc trực tiếp file này, nó sẽ báo cột có nhiều `NaN` và schema bình thường. Khi LLM viết code lọc: `df[df['Trạng thái'] == 'completed']`, nó sẽ **vô tình vứt bỏ sạch 47% số dòng chi tiết hàng hóa**! Hậu quả là tính doanh thu sai lệch nghiêm trọng (như `q_e7837d5638fb`: model tính ra 252.854.400 thay vì 248.572.900 của gold).
   - $\rightarrow$ **Yêu cầu bắt buộc:** Bắt buộc phải có tầng tiền xử lý phát hiện ô gộp và **Forward-fill (điền xuôi dữ liệu cấp cha xuống dòng con)** trước khi lập bản đồ schema!

2. **Sự hỗn loạn về Nhãn trạng thái & Ngôn ngữ Tiếng Việt:**
   - Cùng một trạng thái đơn hàng thành công, mỗi shop viết một kiểu:
     - `biz_101`: Ghi là `Xong`.
     - `biz_111`, `biz_127`, `biz_129`: Ghi là `completed`.
     - Shop khác: `Đã giao`, `Thành công`, `Hoàn thành`, `Đã thanh toán`.
   - Cả 7 câu trong run thử nghiệm đều chết vì gán cứng `.str.contains("hoàn thành")`. Naive profiling nếu chỉ cung cấp tên cột mà không trích xuất toàn bộ tập giá trị rời rạc (`unique_values`) của cột trạng thái thì LLM sẽ tiếp tục mang thiên kiến từ tập SFT áp vào và chết 100%.

3. **Hỗn loạn Định dạng Thời gian (Date/Time Chaos):**
   - File SQLite của BTC lưu cột `NgayLap` dưới dạng chuỗi hỗn tạp: `25/05/2026`, `25 thg 5 2026`, và số nguyên serial của Excel (ví dụ `46167`) lẫn lộn trong cùng một cột (`q_2ea34572153a`).
   - LLM viết câu truy vấn SQL so sánh chuỗi ISO: `WHERE NgayLap >= '2026-05-18'` $\rightarrow$ Trả về **0 dòng**!
   - Các câu hỏi so sánh cùng kỳ ("so với cùng kỳ tháng trước"): Model tự sinh code tạo kỳ trước `01/07 – 30/06` (ngày kết thúc trước ngày bắt đầu!) $\rightarrow$ Mẫu số bằng 0 $\rightarrow$ Lỗi chia cho 0 (`q_d401c0884402`).

4. **Lịch Âm / Dương & Quy ước Dịp Tết (`calendar.csv`):**
   - `docs/data.md` quy định: Dịp Tết tính từ **23 tháng Chạp đến hết mùng 10 Tết** (theo Âm lịch).
   - File `calendar.csv` chứa bảng tra cứu ngày Dương sang ngày Âm. Nếu Bước 1 không phân giải sẵn mốc thời gian này mà bắt LLM tự viết code join với `calendar.csv` trong sandbox, xác suất sinh lỗi join ngày và lệch khung thời gian là cực kỳ cao.

---

### 2.4. Các Chế độ Lỗi Sinh mã (Code Generation) & Bounded Sandbox

Khi khảo sát mã nguồn sandbox hiện tại (`src/agent/sandbox.py`) và nhật ký chạy thử, có 5 chế độ lỗi chết người mà vòng lặp phản hồi 3 bước chưa xử lý được:

| Chế độ Lỗi | Nguyên nhân Gốc rễ | Hiện tượng trong `failure_analysis.md` | Hạn chế của 3-Step Feedback |
|---|---|---|---|
| **Pandas Suffix Collision (`KeyError`)** | Khi merge 2 bảng có cùng tên cột (ví dụ `Tên hàng`, `Thời gian`), pandas tự động đổi tên thành `Tên hàng_x`, `Tên hàng_y`. | `q_019ec94d9799`, `q_e9930d87abdd`: Code sau merge vẫn truy cập `df['Tên hàng']`, gây `KeyError`. Model lặp lại y hệt lỗi này cả 3 lượt! | Phản hồi lỗi chung chung của sandbox khiến LLM 14B không nhận diện được tên cột mới sinh ra sau phép merge. |
| **Dtype Mismatch & Dirty Numbers (`TypeError`)** | Cột tiền tệ hoặc số lượng chứa dấu phẩy `,` (ví dụ `"120,000"`), ký tự `"đ"`, hoặc chuỗi rỗng `""`. | `q_aacf9543a235`: Đưa cột tiền chưa parse vào `.groupby().sum()`, sinh lỗi `unsupported operand type(s) for +: 'int' and 'str'`. | LLM không biết tự chèn hàm làm sạch số nếu schema chỉ báo kiểu `object`. |
| **Silent Logic Failure (12/19 câu sai chốt ngay Lượt 1)** | Code chạy trơn tru, returncode=0, không có exception, nhưng thuật toán tổng hợp sai cấp độ (aggregation level mismatch). | `q_02a70ea566f1`: Top 3 lấy theo dòng lẻ thay vì gom theo sản phẩm; `q_67297f4bdfc2`: Tỉ lệ hủy lấy mã đơn chia cho số dòng lẻ. | Sandbox không thể bắt được lỗi này vì cú pháp hoàn toàn hợp lệ! Bước 3 nếu không có logic so sánh tổng thể sẽ cho qua 100%. |
| **Division by Zero & Float NaN Protocol Violation** | Lọc rỗng dẫn đến `len=0` hoặc mẫu số $=0$, sinh ra `float('nan')` hoặc `inf`. | `q_132add5002d2`: Tính trung bình trên tập rỗng rồi ép kiểu `int(NaN)`, văng `ValueError: cannot convert float NaN to integer`. | Bước 3 nếu chỉ kiểm tra sau khi code chạy xong thì exception đã làm sập script ở sandbox trước đó. |
| **Sandbox Execution Timeout** | Data package lớn (300.000 dòng, nhiều file Excel). LLM viết vòng lặp `for row in df.iterrows()` hoặc regex phức tạp. | Timeout ngưỡng 15s bị kích hoạt (`src/agent/solver.py`, line 723). | Vòng lặp observation không có cơ chế tối ưu vector hóa, lượt sau model vẫn có xu hướng viết lại thuật toán lặp tương tự. |

---

### 2.5. Năm Điểm mù Nghiêm trọng Hoàn toàn Bị Bỏ quên

1. **Điểm mù 1: Nhầm lẫn ranh giới giữa Tiền xử lý Tất định (Deterministic Pre-processing) và Thăm dò Runtime (In-flight Exploration)**
   - Đề xuất dồn toàn bộ gánh nặng tìm hiểu dữ liệu cho LLM thông qua lượt sinh code khám phá ở Bước 2.
   - Đây là sự lãng phí tài nguyên khủng khiếp: Mọi thao tác như đọc danh sách file, trích xuất cấu trúc bảng, kiểm tra ô gộp, quét giá trị nhãn trạng thái (`unique categorical values`), nhận diện định dạng ngày tháng **hoàn toàn có thể thực hiện trước bằng mã Python thuần trong 0.2 giây mà không tốn một token LLM nào!**

2. **Điểm mù 2: Tuân thủ Quy tắc Nghiệp vụ Chung (`rulebook.md`) & Logic Tính toán Đa tầng**
   - Đề xuất 3 bước chỉ tập trung vào "khớp schema và khớp nhãn". Nhưng nguyên nhân cốt lõi khiến 12/19 câu bị sai lại nằm ở **vi phạm quy tắc nghiệp vụ**:
     - Doanh thu chuẩn (`rulebook.md`, Mục 4): Phải bằng tổng tiền dòng sau chiết khấu dòng, **không trừ voucher toàn đơn**, **không cộng VAT**, **không cộng phí ship**, **phải loại trừ toàn bộ đơn có chứa mặt hàng bị trả lại**!
     - Công nợ: Phải phân biệt rõ số nợ snapshot tại thời điểm xuất file và lịch sử dòng tiền trong sổ quỹ (`q_3b5c9002b013`, `q_43df08e6cce8`). Quy tắc yêu cầu **loại trừ COD/giao hàng**. Model lại đi lọc *chỉ lấy COD*.
   - Khám phá schema không thể giải quyết được việc model hiểu sai công thức nghiệp vụ. Cần có prompt template định hướng công thức chuẩn mực cho các chỉ số này.

3. **Điểm mù 3: Nguy cơ Sai lệch Tái lập (Reproducibility Drift) vi phạm Thể lệ Cuộc thi**
   - Thể lệ cuộc thi (`docs/rule.md`, Quy định 8) bắt buộc:
     $$|\text{PA}_{\text{uploaded}} - \text{PA}_{\text{re-run}}| \le 0.03$$
   - Khi áp dụng vòng lặp multi-turn nhiều nhánh rẽ (Turn 1 $\rightarrow$ Sandbox $\rightarrow$ Turn 2 $\rightarrow$ Sandbox $\rightarrow$ Turn 3), tính bất định tăng theo cấp số nhân. Dù đã đặt `temperature=0.0`, sai số dấu phẩy động trong quá trình batching song song trên GPU Blackwell vẫn có thể khiến 5 - 10 câu hỏi rẽ sang nhánh khác giữa 2 lần chạy.
   - Chỉ cần 8 câu hỏi trên 500 câu bị đổi từ Đúng (+1) sang Sai (-1), độ lệch điểm số là $\frac{8 \times 2}{500} = 0.032 > 0.03 \rightarrow$ **BÀI THI BỊ LOẠI TRỰC TIẾP (DISQUALIFIED)!** Pipeline càng ít bước rẽ nhánh ngẫu nhiên, độ an toàn tái lập càng cao.

4. **Điểm mù 4: Ranh giới Mong manh giữa `unanswerable` và `abstain`**
   - Theo `docs/evaluation.md`:
     - Trả lời giá trị cụ thể cho câu không thể trả lời $\rightarrow$ **SAI (-1.0 điểm)**.
     - Trả lời `unanswerable` cho câu có thể trả lời $\rightarrow$ **SAI (-1.0 điểm)**.
     - Trả lời `abstain` cho bất kỳ câu nào $\rightarrow$ **0.0 điểm an toàn**.
   - Trong 30 câu dev, có 3 câu gold là `unanswerable` (`q_22f59bab1075`, `q_95099c4916a8`, `q_fcafb39ec35f`). Cả 3 câu này model đều cố gắng trả lời và bị phạt -1.0 điểm!
   - Ngược lại, có 2 câu trả lời được nhưng do lọc sai ra rỗng nên model chốt `unanswerable` (`q_554d736852a5`, `q_e0aef192cb11`) và cũng bị phạt -1.0 điểm!
   - Đề xuất 3 bước hoàn toàn không có tiêu chí phân định khi nào một kết quả rỗng là do dữ liệu thiếu thật sự (`unanswerable`) hay do code viết lỗi. Trong trường hợp mơ hồ này, **luôn luôn trả về `abstain` là chiến lược tối ưu toán học duy nhất**.

5. **Điểm mù 5: Sự Xung đột Cú pháp giữa SQLite và Excel/CSV**
   - Các shop trong bài thi dùng hỗn hợp: có shop dùng 1 file `.sqlite`, có shop dùng 10 file `.xlsx`, có shop dùng cả hai.
   - Code do LLM sinh thường xuyên lẫn lộn giữa hàm SQLite (`strftime`, `julianday`) và hàm Pandas (`pd.to_datetime`, `.dt.strftime`). Thậm chí model mở kết nối SQLite nhưng lại dùng cú pháp truy vấn không tương thích với kiểu lưu trữ động của SQLite (chẳng hạn lưu ngày kiểu text DD/MM/YYYY nhưng lại `ORDER BY NgayLap`).

---

## 3. R4. TỔNG KẾT ĐÁNH GIÁ & KHUYẾN NGHỊ ĐIỀU CHỈNH

### 3.1. Phán quyết Kiến trúc (Architectural Verdict)

| Hạng mục | Đánh giá | Rủi ro chính |
|---|---|---|
| **Ý tưởng Cốt lõi** | **HỢP LÝ VỀ MẶT MỤC TIÊU** | Hướng đúng vào các nguyên nhân gây lỗi chính (schema, nhãn lọc, kết quả rỗng). |
| **Cách thức Thực thi Đề xuất** | **KHÔNG KHẢ THI (FLAWED)** | Phụ thuộc vào vòng lặp hội thoại đa lượt của LLM; làm bùng nổ latency; đối mặt nguy cơ timeout 6 giờ; rơi vào bẫy ảo giác retry làm giảm PA. |
| **Định hướng Cải tiến** | **DETERMINISTIC TRANSFORMATION** | Chuyển đổi toàn bộ Bước 1 & 2 thành **Module Tiền xử lý Tĩnh (Deterministic Pre-profiler)** chạy bằng Python trước khi gọi LLM. Giữ pipeline LLM ở dạng **Single-turn sinh mã chuẩn xác**, có hậu kiểm bằng **Hard Abstain Gate**. |

---

### 3.2. Những điểm CẦN GIỮ LẠI (What to Keep)

1. **Bản đồ dữ liệu tinh gọn (Compact Schema Mapping):**
   - Trích xuất danh sách file thực tế trong `BUSINESS_DIR`, danh sách sheet, danh sách cột chính xác kèm kiểu dữ liệu thực tế.
   - Hiển thị rõ số lượng dòng (`row_count`) và định dạng ngày quan sát được (`observed date range`).
2. **Trích xuất mẫu nhãn giá trị rời rạc (Categorical Value Profiling):**
   - Đối với các cột có độ biến thiên thấp ($\le 30$ giá trị duy nhất, đặc biệt là các cột trạng thái đơn, hình thức thanh toán, loại khách), trích xuất và đưa toàn bộ danh sách giá trị vào prompt (ví dụ: `Trạng thái: ['Xong', 'Đang xử lý']` hoặc `['completed', 'cancelled']`).
   - Điều này triệt tiêu tận gốc 100% các lỗi chết người dạng `.str.contains("hoàn thành")` mà không cần tốn lượt khám phá nào.
3. **Bộ lọc Hậu kiểm Kết quả Nghi ngờ (Suspicious Result Sanity Check):**
   - Giữ lại các tiêu chí cảnh báo: Kết quả tính ra `0` đối với doanh thu/sản lượng, danh sách rỗng `[]`, bảng rỗng `{"rows": []}`, số dòng sau lọc bằng 0, hoặc giá trị âm vô lý đối với số đếm.

---

### 3.3. Những điểm CẦN ĐIỀU CHỈNH & BỔ SUNG (What to Adjust / Enhance)

```
[ĐỀ XUẤT CŨ - DỄ ĐỔ VỠ]
LLM Turn 1 (Sinh code khám phá) 
  --> Bounded Sandbox (Thực thi) 
  --> LLM Turn 2 (Nhận observation, sinh code tính toán) 
  --> Bounded Sandbox (Thực thi) 
  --> LLM Turn 3 (Retry nếu kết quả nghi ngờ) 
  ==> Tốn 35-55s/câu, KV-cache phình to, dễ hallucinate retry.

[KIẾN TRÚC MỚI KHUYẾN NGHỊ - BẢO TOÀN PA & TỐC ĐỘ CAO]
Bước 0: Deterministic Ingestion & Profiler (Python thuần, ~0.2s)
  - Auto-unmerge / Forward-fill ô gộp Excel
  - Chuẩn hóa ngày tháng đa định dạng sang ISO chuẩn
  - Quét toàn bộ unique status/categories
  - Phân giải khung thời gian (Lunar/Solar, Tết, as_of_date)
        │
        ▼
Bước 1: Single-turn Prompt Giàu Ngữ Cảnh (Rich Single-Turn Context)
  - Schema sạch + Danh sách nhãn thực tế + Mốc ngày tường minh [start, end]
  - Code template an toàn (tránh va chạm hậu tố _x/_y, công thức doanh thu)
        │
        ▼
Bước 2: LLM Sinh Mã Thực Thi Trực Tiếp (Single-Turn Code Generation, ~10s)
  - Code Python đọc dữ liệu sạch và xuất JSON final
        │
        ▼
Bước 3: Hard Deterministic Abstain Gate (Hậu kiểm An toàn PA)
  - Kiểm tra kết quả: Nếu hợp lệ và tin cậy cao (p > 0.8) --> Chốt kết quả (+1.0)
  - Nếu kết quả nghi ngờ (0 dòng, rỗng, NaN, lỗi tính toán) -->
      * Kiểm tra xem có fallback tất định không.
      * NẾU KHÔNG: CẮT LỖ BẰNG `type="abstain"` NGAY LẬP TỨC (Bảo toàn 0.0 điểm, chặn đứng -1.0 phạt).
```

#### Các chi tiết kỹ thuật cần bổ sung:
1. **Thay thế Bước 2 bằng "Deterministic Pre-Profiler" (Bước 0):**
   - Không cho model sinh code để "khám phá". Mọi thứ model cần khám phá đã được bộ profiler Python chạy ngầm quét sẵn trong 200ms khi nạp shop.
   - Nhúng trực tiếp các giá trị quan sát được vào prompt lượt đầu. LLM chỉ cần làm 1 việc duy nhất: **Sinh script tính toán chính xác trong 1 lượt (Single-turn)**.
2. **Chuyển Bước 3 thành Cổng Từ chối Cứng (Hard Abstain Gate):**
   - Loại bỏ hoàn toàn vòng lặp retry tự do khi gặp kết quả nghi ngờ.
   - Thiết lập quy tắc quyết định theo lý thuyết thông tin:
     - Nếu câu hỏi hỏi một thực thể hoàn toàn không xuất hiện trong database (sau khi đã chuẩn hóa không dấu): Nếu rulebook khẳng định thiếu dữ liệu là `unanswerable`, trả lời `unanswerable`; nếu không chắc chắn 100%, trả về **`abstain`**.
     - Nếu code lọc ra 0 dòng hoặc gặp exception: Trả về **`abstain`** (0 điểm), tuyệt đối không để LLM đoán mò số liệu.
3. **Trang bị "Code Guards / Safe Join Templates" trong Prompt:**
   - Hướng dẫn model luôn chỉ định hậu tố rõ ràng khi merge: `pd.merge(df1, df2, on='Mã đơn', suffixes=('_don', '_hang'))`.
   - Cung cấp sẵn hàm chuẩn hóa số an toàn: `pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)`.

---

### 3.4. Lộ trình Kỹ thuật Ưu tiên Thực thi (Prioritized Engineering Roadmap)

> **CẢNH BÁO QUAN TRỌNG:**  
> **TUYỆT ĐỐI CHƯA NÊN TRAIN LẠI MODEL VÀO LÚC NÀY!**  
> Kết quả phân tích 30 câu trong `failure_analysis.md` cho thấy 100% các ca thất bại xuất phát từ:
> - Dữ liệu ô gộp chưa được forward-fill (47% dữ liệu mất hút).
> - Nhãn trạng thái không khớp (`Xong`/`completed` vs `hoàn thành`).
> - Ngày tháng sai định dạng và sai kỳ so sánh.
> - Lỗi cú pháp merge bảng pandas (`KeyError` do suffix).
> - Sai công thức nghiệp vụ (tính trên dòng thay vì gom nhóm).  
>
> Đây đều là các vấn đề thuộc về **Kỹ thuật Tiền xử lý Dữ liệu, Prompt Engineering và Guardrails**. Việc mang một bộ dữ liệu bẩn và pipeline lỗi đi fine-tune chỉ làm mô hình học thêm các thói quen xấu (như 38/817 mẫu SFT cũ đã bị tiêm nhiễm mã `.str.contains("hoàn thành")`).  
> Đội ngũ phát triển cần tập trung hoàn thiện hệ thống kỹ thuật theo thứ tự ưu tiên dưới đây:

```
┌────────────────────────────────────────────────────────────────────────┐
│             LỘ TRÌNH KỸ THUẬT ƯU TIÊN (PRIORITIZED ROADMAP)            │
└────────────────────────────────────────────────────────────────────────┘

[ƯU TIÊN 1] Robust Data Ingestion & Auto-Unmerger
 ├── Module: `src/profiler/business_loader.py`
 ├── Hành động: 
 │    - Tự động phát hiện ô gộp và Forward-fill trên các sheet Excel
 │    - Phục hồi ngữ cảnh cấp đơn (Mã đơn, Ngày, Trạng thái) cho các dòng chi tiết
 │    - Xây dựng Universal Date Parser (xử lý ISO, DD/MM/YYYY, '25 thg 5', Excel serial)
 └── Mục tiêu: Giải quyết ngay lập tức các lỗi mất 47% dữ liệu ở biz_121, biz_122.

[ƯU TIÊN 2] Categorical Value Profiler & Value Indexer
 ├── Module: `src/profiler/business_loader.py`
 ├── Hành động:
 │    - Quét và trích xuất 100% unique values của các cột phân loại (<= 30 nhãn)
 │    - Đưa trực tiếp danh sách nhãn vào schema prompt
 └── Mục tiêu: Xóa sổ hoàn toàn lỗi rỗng dữ liệu do lệch nhãn trạng thái (biz_101, biz_111...).

[ƯU TIÊN 3] Time Resolver & Rulebook Engine Hoàn thiện
 ├── Module: `src/time_resolver/calendar_utils.py`
 ├── Hành động:
 │    - Tích hợp tra cứu Âm - Dương từ `calendar.csv` cho khung Tết
 │    - Mở rộng phân giải thời gian tương đối: Tính toán sẵn ngày [start, end]
 │      cho "tháng này", "tuần trước", "cùng kỳ tháng trước"
 └── Mục tiêu: Triệt tiêu lỗi tạo kỳ ngược (01/07-30/06) và lỗi chuỗi ngày SQLite.

[ƯU TIÊN 4] Hard Deterministic Abstain Gate & Output Normalizer
 ├── Module: `src/agent/sandbox.py` & `src/agent/solver.py`
 ├── Hành động:
 │    - Kích hoạt bắt buộc cổng kiểm duyệt: Chặn đứng mọi kết quả 0, [], NaN
 │    - Áp dụng nguyên tắc toán học: E[PA] = 2p - 1. Nếu p < 0.5 --> Chuyển sang 'abstain'
 │    - Chuẩn hóa triệt để Unicode NFC, định dạng số tiền, số lượng theo đúng spec
 └── Mục tiêu: Bảo toàn điểm số, chặn đứng điểm phạt -1.0 từ các ca hallucination.

[ƯU TIÊN 5] Prompt Optimization & Safe Code Templates
 ├── Module: `src/agent/prompts.py`
 ├── Hành động:
 │    - Thêm chỉ dẫn cú pháp merge an toàn (tránh đụng độ hậu tố _x, _y)
 │    - Bổ sung công thức mẫu cho các chỉ số cốt lõi (Doanh thu theo dòng, Bán chạy theo số lượng)
 │    - Cung cấp vài ví dụ (few-shot) cô đọng về cách gom nhóm trước khi lấy top
 └── Mục tiêu: Nâng cao tỷ lệ đúng ngay Lượt 1 từ 4/30 lên > 20/30 câu.

[ƯU TIÊN 6] (BƯỚC CUỐI CÙNG) Fine-Tuning / SFT Model với Dữ liệu Chuẩn hóa
 ├── Module: `scripts/train_sft_lora.py`
 ├── Điều kiện kích hoạt: CHỈ TIẾN HÀNH KHI Ưu tiên 1 -> 5 đã hoàn thành và đạt PA > +0.50 trên Dev Set.
 ├── Hành động:
 │    - Lọc bỏ 38 mẫu lỗi `.str.contains("hoàn thành")` trong tập SFT 817 mẫu
 │    - Sinh lại bộ mẫu huấn luyện phản ánh đúng pipeline tiền xử lý mới
 │    - Train LoRA với cấu hình kiểm soát chặt chẽ tính tất định.
 └── Mục tiêu: Đạt PA tối đa trên Public & Private Leaderboard.
```

---
*Báo cáo được hoàn thành độc lập và khách quan bởi Teamwork Critic Agent.*
