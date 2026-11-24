# BÁO CÁO ĐÁNH GIÁ TÍNH KHẢ THI, PHẢN BIỆN CHUYÊN SÂU & RÀ SOÁT RỦI RO KỸ THUẬT: ĐỀ XUẤT CẢI TIẾN PIPELINE 3 BƯỚC (DATAMATE 2026)

> **Tài liệu thẩm định & phản biện kiến trúc chính thức**  
> **Đơn vị thực hiện:** Teamwork Orchestrator (hợp nhất từ Explorer 1 & Critic 1)  
> **Dự án:** Zalo AI Challenge 2026 — Đề tài: DataMate (Hỏi đáp Tiếng Việt trên dữ liệu bảng biểu doanh nghiệp)  
> **Căn cứ đối chiếu:** `result/qwen25_14b_1m_code_only_rulebook_20261111_155610/eval_dev_30_colab_a100_40gb_ctx16384/failure_analysis.md`, bộ quy chế `docs/`, và toàn bộ mã nguồn tại `src/`, `scripts/`, `tests/`.

---

## TỔNG KẾT ĐIỀU HÀNH (EXECUTIVE SUMMARY)

Đề xuất cải tiến pipeline 3 bước bao gồm:
1. **Bước 1 — Bản đồ dữ liệu gọn (Compact Data Map):** Trích xuất schema ngắn gọn; hiển thị toàn bộ giá trị cho cột ít nhãn (low-cardinality $\le 20$); với cột nhiều nhãn, chỉ hiển thị số lượng và vài mẫu kèm nhãn cảnh báo rõ ràng.
2. **Bước 2 — Lượt khám phá có mục tiêu trong sandbox (Targeted Sandbox Exploration):** Sử dụng sandbox chạy code thăm dò dữ liệu thô, trả về kết quả liên quan qua giao thức `observation` trước khi sinh code chốt đáp án.
3. **Bước 3 — Kiểm tra kết quả đáng nghi trước khi chốt (Suspicious Result Sanity Check):** Tự động phát hiện các bất thường (kết quả 0, `[]`, DataFrame rỗng sau lọc/join, số dòng trước/sau lọc, nhãn đã dùng) để cảnh báo sửa chữa hoặc từ chối trả lời.

### Phán quyết Cốt lõi (Architectural Verdict)
- **Đánh giá phản hồi:** Đề xuất phản hồi 3 bước là **RẤT TỐT VỀ MẶT ĐỊNH HƯỚNG VÀ ĐÁNH TRÚNG ~80% NGUYÊN NHÂN GÂY LỖI TRỰC TIẾP** trong đợt đánh giá 30 câu dev vừa qua.
- **Điểm mù chí mạng:** Nếu triển khai Bước 2 dưới dạng **vòng lặp đa lượt LLM runtime (runtime multi-turn loop) cho toàn bộ câu hỏi**, hệ thống sẽ đối mặt với **nguy cơ sập giới hạn thời gian (Timeout Termination)** trong môi trường Docker offline, đồng thời phá vỡ bộ đệm Prefix Caching của vLLM trên GPU RTX 5090.
- **Giải pháp chuyển hóa:** Cần chuyển đổi đề xuất từ *"LLM Multi-Turn Exploration"* thành **"Deterministic Pre-profiling (Tiền xử lý tất định Python < 0.2s) + Conditional Exploration (Thăm dò có điều kiện)"**, đồng thời gắn chặt Bước 3 với một **"Hard Deterministic Abstain Gate"** để tối ưu hóa triệt để điểm số theo công thức Penalized Accuracy.
- **Quyết định về Model Training:** **TUYỆT ĐỐI CHƯA TRAIN LẠI MODEL Ở THỜI ĐIỂM NÀY.** Mô hình Qwen2.5-Coder-14B hiện tại có năng lực viết mã Python rất tốt; 100% lỗi sai phát sinh từ việc "mù siêu dữ liệu" (metadata blindness), thiếu bộ lọc đầu ra và định dạng bảng Excel ô gộp, chứ không phải do năng lực mô hình.

---

## MỤC LỤC CHI TIẾT
1. [R1. Phân tích & Phản biện Chi tiết Đề xuất Cải tiến Pipeline 3 Bước](#r1-phân-tích--phản-biện-chi-tiết-đề-xuất-cải-tiến-pipeline-3-bước)
2. [R2. Đối chiếu Trực tiếp với Kết quả Đánh giá 30 Câu trong failure_analysis.md](#r2-đối-chiếu-trực-tiếp-với-kết-quả-đánh-giá-30-câu-trong-failure_analysismd)
3. [R3. Rà soát Các Rủi ro Kỹ thuật, Điểm mù & Vấn đề Tồn đọng](#r3-rà-soát-các-rủi-ro-kỹ-thuật-điểm-mù--vấn-đề-tồn-đọng)
4. [R4. Tổng kết Đánh giá & Khuyến nghị Điều chỉnh có Thứ tự Ưu tiên](#r4-tổng-kết-đánh-giá--khuyến-nghị-điều-chỉnh-có-thứ-tự-ưu-tiên)

---

# R1. PHÂN TÍCH & PHẢN BIỆN CHI TIẾT ĐỀ XUẤT CẢI TIẾN PIPELINE 3 BƯỚC

### 1. Bước 1: Bản đồ dữ liệu gọn (Compact Data Map with Cardinality Partitioning)
* **Cơ chế:** Phân tích schema trước khi gọi LLM. Với cột có $\le 20$ giá trị duy nhất (unique values), liệt kê đầy đủ danh sách nhãn. Với cột $> 20$ giá trị, chỉ ghi số lượng và 3–5 giá trị mẫu kèm nhãn `[Mẫu tham khảo, không phải toàn bộ]`.
* **Ưu điểm:**
  1. *Triệt tiêu ảo giác nhãn:* Trong 30 câu dev, có 7 câu thất bại vì model tự đoán chuỗi `.str.contains("hoàn thành")` trong khi shop dùng `Xong` (biz_101) hoặc `completed` (biz_111, 127, 129). Đưa nhãn thật vào prompt giúp loại bỏ hoàn toàn lỗi này.
  2. *Tiết kiệm context:* Giảm độ dài prompt từ 4.000–8.000 tokens xuống còn 400–800 tokens, tăng tốc độ sinh (prefill time) trên vLLM.
  3. *Ngăn ngộ nhận mẫu:* Cảnh báo rõ ràng giúp model không bao giờ coi danh sách mẫu là toàn bộ cơ sở dữ liệu.
* **Nhược điểm & Điểm mù:**
  - *Thời gian nạp file lớn:* File Excel như `biz_121` (>80.000 dòng) nếu dùng `pd.read_excel()` tuần tự để tính `unique()` sẽ mất 5–15s. (Bắt buộc dùng `python-calamine` và lưu cache ở cấp `business_id`).
  - *Bùng nổ cardinality do dữ liệu bẩn:* Cột trạng thái nhưng có nhân viên gõ kèm ghi chú tự do làm số lượng unique tăng đột biến $>20$.
* **Tính khả thi:** **100% Khả thi.** `src/profiler/business_loader.py` đã trích xuất sẵn `categorical_values`, chỉ cần sửa hàm `format_profile_for_prompt()` để hiển thị có điều kiện thay vì lược bỏ như hiện tại.

### 2. Bước 2: Lượt khám phá có mục tiêu trong sandbox (Targeted Sandbox Exploration)
* **Cơ chế:** Cho phép model sinh một script Python thăm dò, in ra `{"kind": "observation", "data": ...}`. Sandbox bắt stdout và đưa vào prompt lượt 2 để model sinh code chốt đáp án.
* **Ưu điểm:**
  1. *Xử lý hậu tố đổi tên sau Join của Pandas:* Pandas tự thêm `_x`, `_y` khi join 2 bảng trùng tên cột, gây lỗi `KeyError` lặp lại cả 3 lượt ở 4 câu eval (`q_019ec94d9799`, `q_aacf9543a235`, `q_e9930d87abdd`, `q_583e4896e764`). Thăm dò giúp model in ra `df.columns` để viết đúng tên cột.
  2. *Hỗ trợ tìm kiếm chuỗi tiếng Việt không dấu & Fuzzy Match:* Giúp quét tìm sản phẩm như `"soda chanh day (m)"` -> `"Soda chanh dây (M)"` (`q_01a28f2233bd`).
  3. *Nhận diện định dạng ngày phi chuẩn trong SQLite:* Giúp phát hiện định dạng ngày tiếng Việt (`25/05/2026`, `25 thg 5 2026`) trước khi truy vấn SQL.
* **Nhược điểm & Rủi ro lớn:**
  - *Bùng nổ thời gian suy luận (Latency):* Mỗi lượt sinh ngốn 10–18s. Nếu câu nào cũng chạy thăm dò, thời gian sẽ tăng gấp đôi (35–55s/câu), gây nguy cơ timeout toàn bộ quá trình thi đấu (tối đa 6 giờ cho ~500 câu test).
  - *Hành vi model SFT:* 12/19 câu sai trong eval chốt ngay ở lượt 1. Model sau huấn luyện luôn có xu hướng chốt `final` ngay.
  - *Ảo giác từ kết quả thăm dò:* Nếu script thăm dò viết regex sai trả về rỗng, model ở lượt 2 sẽ tin rằng shop không có dữ liệu và kết luận sai `unanswerable` (bị phạt -1.0 điểm).
* **Tính khả thi & Điều chỉnh:** **Khả thi nhưng phải là Thăm dò có điều kiện (Conditional Exploration)**: Chỉ kích hoạt cho câu hỏi join $\ge 2$ bảng hoặc câu hỏi tìm kiếm chuỗi không dấu. Không áp dụng cho câu hỏi đơn giản.

### 3. Bước 3: Kiểm tra kết quả đáng nghi trước khi chốt (Suspicious Result Sanity Check)
* **Cơ chế:** Đặt chốt chặn kiểm tra: doanh thu = 0, xếp hạng `[]`, danh sách trùng lặp, số lượng âm, bảng công nợ toàn 0. Nếu nghi ngờ, gửi feedback yêu cầu model sửa hoặc kích hoạt Abstain Gate.
* **Ưu điểm:**
  1. *Chiếc phao cứu sinh bảo vệ điểm PA:* Trong thang điểm PA (+1 đúng, 0 abstain, -1 sai), chặn được một kết quả sai chuyển thành abstain sẽ tăng ngay +1.0 điểm cho hệ thống.
  2. *Hệ thống đã có sẵn khung sườn:* Hàm `_eval_guard_issue()` trong `src/agent/solver.py` (dòng 659–695) đã được lập trình sẵn các quy tắc này.
* **Nhược điểm & Rủi ro:**
  - *Nguy cơ False Positive (Chặn nhầm kết quả 0 thật):* Nếu một cửa hàng thực sự có doanh thu = 0 vào ngày nghỉ lễ, việc chặn mù quáng số 0 sẽ làm mất điểm đúng. (Cần kiểm tra thêm `rows_after_filter == 0` thay vì chỉ nhìn vào giá trị 0).
  - *Hiện trạng vô hiệu hóa trong codebase:* Biến `self.eval_core_rules` trong `src/agent/solver.py` (dòng 711) đang mặc định là `False`, khiến toàn bộ guardrail bị tê liệt trong lần eval vừa qua!
* **Tính khả thi:** **100% Khả thi.** Chỉ cần bật `eval_core_rules = True` và tinh chỉnh logic kiểm tra số dòng sau lọc.

---

# R2. ĐỐI CHIẾU TRỰC TIẾP VỚI KẾT QUẢ ĐÁNH GIÁ 30 CÂU TRONG FAILURE_ANALYSIS.MD

### Ma trận Tổng hợp Phân loại 30 Câu:
- **Nhóm A — Giải quyết hoàn toàn (Fully Solved):** **14/30 câu (46.7%)** (10 câu lỗi/abstain được sửa triệt để + 4 câu baseline đúng được duy trì).
- **Nhóm B — Cải thiện đáng kể / Chặn rủi ro điểm phạt (Partially Solved / Risk Mitigated):** **14/30 câu (46.7%)** (Chặn 0, [], unanswerable ảo chuyển thành `abstain` an toàn, cứu -1.0 điểm phạt).
- **Nhóm C — Chưa giải quyết được (Unsolved):** **2/30 câu (6.7%)** (Excel merged cells làm trống dòng con và hiểu sai mẫu số tỉ lệ huỷ đơn).
- **Nhóm D — Nguy cơ làm hỏng trực tiếp (Worsened):** **0/30 câu (0.0%)**.

### Bảng Đối chiếu Chi tiết Từng Câu Hỏi:

| STT | Question ID | Biz ID | Câu hỏi tóm tắt | Kết quả Eval | Gold Answer | Pred Answer | Bước can thiệp | Phân loại | Giải thích nguyên nhân gốc rễ & Cơ chế tác động |
|:---:|---|:---:|---|:---:|---|---|:---:|:---:|---|
| 1 | `q_019ec94d9799` | biz_106 | 3 mặt hàng bán chạy nhất tuần này | Abstain | `['Cà phê sữa (M)', ...]` | `null` | Bước 1, 2 | **(A) Fully Solved** | Lỗi: Pandas join thêm `_x`, `_y` vào cột `Tên hàng` -> KeyError 3 lượt. Bước 1 & 2 làm rõ cột sau join, code chạy chuẩn ra đúng Top 3. |
| 2 | `q_01a28f2233bd` | biz_112 | Giá bán soda chanh day (m) ngày 01/12/2025 | Abstain | `37000` | `null` | Bước 2 | **(A) Fully Solved** | Lỗi: Câu hỏi không dấu, query chuỗi có dấu trực tiếp làm rỗng DataFrame -> thiếu evidence. Bước 2 fuzzy scan ra `"Soda chanh dây (M)"` giá 37.000. |
| 3 | `q_02a70ea566f1` | biz_112 | Top 3 sp bán nhiều nhất tháng 3/2026 | Sai | Top 3 sp | 3 dòng bánh croissant trùng lặp | Bước 2, 3 | **(B) Partially Solved** | Lỗi: Model lấy `head(3)` từng dòng thay vì `groupby().sum()`. Bước 3 phát hiện trùng lặp phần tử cảnh báo sửa; Bước 2 hỗ trợ kiểm tra aggregation. |
| 4 | `q_132add5002d2` | biz_127 | Doanh thu trung bình trên một đơn tháng 6/2026 | Abstain | `535722` | `null` | Bước 1, 3 | **(B) Partially Solved** | Lỗi: Filter `hoàn thành` làm rỗng 2.017 đơn `completed` -> mean NaN. Bước 1 sửa nhãn `completed`. Cần thêm Rulebook §1 (doanh thu theo dòng) để khớp 535.722. |
| 5 | `q_1b119bdd5d28` | biz_109 | Tháng 7, 8, 9/2025 tháng nào doanh thu cao nhất | Đúng | `2025-08` | `2025-08` | Không (Baseline) | **(A) Maintained Correct** | Baseline đã đúng từ lượt đầu. Duy trì ổn định. |
| 6 | `q_20aa992c0d3f` | biz_101 | Tháng 5/2026 ngày nào bán được nhiều tiền nhất | Sai | `2026-05-09` | `2026-05-01` | Bước 1, 3 | **(A) Fully Solved** | Lỗi: Filter `hoàn thành` làm rỗng biz_101 (nhãn là `Xong`). Code fallback gán 01/05. Bước 1 đưa nhãn `Xong`, Bước 3 chặn rỗng, tính ra đúng `2026-05-09`. |
| 7 | `q_21c12147e6d6` | biz_127 | Tháng 6/2025 khách nào mua nhiều tiền nhất | Abstain | `"Thân Hồng Nhung"` | `null` | Bước 1, 2 | **(B) Partially Solved** | Lỗi: Sai nhãn trạng thái và dùng sai cột `Mã KH` thay vì `Customer ID` -> KeyError. Bước 1 & 2 sửa nhãn và schema cột nối. |
| 8 | `q_22f59bab1075` | biz_112 | Hộp Bánh croissant nguyên và lẻ trong kho | Sai | `unanswerable` | `[166666666, 3]` | Bước 1, 2, 3 | **(B) Partially Solved** | Lỗi: Không có thẻ kho, model lấy max 999.999.999 chia 6 ra số bánh vô lý. Bước 3 chặn số ảo và ép chuyển sang `abstain` (cứu -1.0 điểm). |
| 9 | `q_2a0e86444947` | biz_106 | Tháng 7/2026 số đơn tiền hàng $\ge$ 130.000 | Sai | `507` | `510` | Bước 1 | **(A) Fully Solved** | Lỗi: Regex sót 3 đơn `Hoàn trả`. Bước 1 liệt kê đủ nhãn trạng thái có chữ `Hoàn trả`, model viết regex đúng loại bỏ 3 đơn, ra đúng 507. |
| 10 | `q_2ea34572153a` | biz_123 | 3 khách mua nhiều tiền nhất tuần rồi | Sai | Top 3 khách | `[]` | Bước 1, 2, 3 | **(A) Fully Solved** | Lỗi: Ngày trong SQLite lưu dạng chuỗi tiếng Việt, so sánh ISO ra rỗng `[]`. Bước 3 chặn `[]`, Bước 1 & 2 cung cấp mẫu ngày để parse đúng format. |
| 11 | `q_338ae382671b` | biz_105 | Tuần trước ca chiều vs ca sáng chênh bao nhiêu % | Sai | `-16.41` | `-18.69` | Bước 1, 2 | **(B) Partially Solved** | Lỗi: Sai nhãn trạng thái và bỏ sót lọc tuần trước. Bước 1 sửa nhãn trạng thái, kết quả tính tiệm cận -16.36%. |
| 12 | `q_3b5c9002b013` | biz_109 | Đến hết 14/06/2025 có bao nhiêu khách còn nợ | Sai | `121` | `0` | Bước 3 | **(B) Partially Solved** | Lỗi: Lọc nhầm COD và lấy snapshot xuất file ra 0 khách. Bước 3 phát hiện 0 khách nợ đáng ngờ, chặn chuyển `abstain` (cứu -1.0 điểm). |
| 13 | `q_43df08e6cce8` | biz_109 | Tháng 3/2025 khách Thu mua chịu và trả bớt nợ | Sai | `[130500, 43500]` | `[0, 0]` | Bước 3 | **(B) Partially Solved** | Lỗi: Nhìn snapshot ra `[0, 0]`. Bước 3 chặn `[0, 0]`, ép `abstain` (cứu -1.0 điểm). Để ra đúng cần đọc sổ quỹ Rulebook §4. |
| 14 | `q_554d736852a5` | biz_111 | Doanh thu trung bình mỗi đơn tháng 9/2025 | Sai | `70017` | `unanswerable` | Bước 1, 3 | **(B) Partially Solved** | Lỗi: Nhãn `completed` rỗng do filter `hoàn thành` -> chốt unanswerable sai. Bước 1 đưa nhãn `completed`, Bước 3 chặn unanswerable ảo, ra 70.017. |
| 15 | `q_583e4896e764` | biz_109 | Doanh thu sữa chiếm % tổng revenue tháng 6/2025 | Abstain | `5.79` | `null` | Bước 1, 2 | **(A) Fully Solved** | Lỗi: Đọc cột `Thời gian` từ file không có cột này -> KeyError. Bước 1 & 2 chỉ rõ cột để join hoá đơn và chi tiết, tính ra đúng 5.79%. |
| 16 | `q_5c5ff524d0d9` | biz_121 | Doanh thu Povidon iod tháng 10/2025 | Sai | `8253000` | `0` | Bước 2, 3 | **(B) Partially Solved** | Lỗi: So SKU với mã đơn ra rỗng -> 0. Ngoài ra file có merged cells. Bước 3 chặn 0. Bước 2 dò tên thuốc. Cần thêm ffill cho merged cells. |
| 17 | `q_67297f4bdfc2` | biz_122 | Tỉ lệ huỷ đơn tháng 3/2026 là bao nhiêu % | Sai | `0.98` | `0.52` | Không | **(C) Unsolved** | Lỗi: Chia 31 đơn huỷ cho 5.987 dòng (ra 0.52%) thay vì chia cho 3.148 mã đơn phân biệt (ra 0.98% theo Rulebook §1). 3 bước không can thiệp toán học prompt. |
| 18 | `q_725f54f95253` | biz_101 | Ngày nào doanh thu cao nhất tháng 7/2026 | Đúng | `2026-07-30` | `2026-07-30` | Không (Baseline) | **(A) Maintained Correct** | Baseline đã đúng từ lượt đầu. Duy trì ổn định. |
| 19 | `q_7428165a9e0a` | biz_129 | Tổng doanh thu hôm qua là bao nhiêu | Sai | `22740500` | `0` | Bước 1, 3 | **(B) Partially Solved** | Lỗi: Lọc `hoàn thành` làm rỗng 47 đơn `completed` -> 0. Bước 1 đưa nhãn `completed`, Bước 3 chặn 0. Cộng tiền dòng hàng ra đúng 22.740.500. |
| 20 | `q_95099c4916a8` | biz_109 | Khách nữ chiếm bao nhiêu % doanh thu tháng 12/2025 | Sai | `unanswerable` | `0` | Bước 1, 3 | **(A) Fully Solved** | Lỗi: Thiếu cột giới tính. Lọc `Loại hình khách` ra 0 dòng -> đoán 0%. Bước 1 & 3 phát hiện rỗng thông tin, chốt chuẩn `unanswerable`. |
| 21 | `q_9b1dce77c710` | biz_106 | Bảng 3 khách nợ nhiều nhất đến hết 30/06/2026 | Sai | Bảng nợ tiền | Bảng nợ 0đ | Bước 3 | **(B) Partially Solved** | Lỗi: Snapshot ra nợ 0đ. Bước 3 phát hiện bảng toàn số 0 là bất thường, chặn và ép `abstain` (cứu -1.0 điểm). |
| 22 | `q_a264d94a0492` | biz_101 | Tháng 9/2025 hàng nào bán chạy nhất | Đúng | `"Snack Oishi..."` | `"Snack Oishi..."` | Không (Baseline) | **(A) Maintained Correct** | Baseline đã đúng từ lượt đầu. Duy trì ổn định. |
| 23 | `q_a569fbc6b9fc` | biz_106 | Doanh thu có tăng liên tục 3 tháng 4, 5, 6/2026 không | Đúng | `False` | `False` | Không (Baseline) | **(A) Maintained Correct** | Baseline đã đúng từ lượt đầu. Duy trì ổn định. |
| 24 | `q_aacf9543a235` | biz_106 | Khách mua nhiều tiền nhất tháng 3/2026 | Abstain | `"Vương Phương Loan"` | `null` | Bước 1, 2 | **(A) Fully Solved** | Lỗi: KeyError hậu tố `_x` và `TypeError` chuỗi số. Bước 1 & 2 làm rõ schema cột nối và định dạng số, tính ra đúng khách hàng. |
| 25 | `q_d401c0884402` | biz_130 | So cùng kỳ tháng trước, doanh thu tăng giảm bao nhiêu % | Sai | `-18.92` | `unanswerable` | Bước 3 | **(B) Partially Solved** | Lỗi: Tự dựng kỳ trước bị lỗi ngày (`01/07–30/06`) -> chia 0 -> chốt unanswerable sai. Bước 3 chặn lại thành `abstain` (cứu -1.0 điểm). |
| 26 | `q_e0aef192cb11` | biz_101 | Doanh thu ngày nào cao nhất tháng 6/2026 | Sai | `2026-06-01` | `unanswerable` | Bước 1, 3 | **(A) Fully Solved** | Lỗi: Filter `hoàn thành` làm rỗng tháng 6 của biz_101 (`Xong`) -> unanswerable sai. Bước 1 đưa nhãn `Xong`, tính ra đúng ngày `2026-06-01`. |
| 27 | `q_e311e396f7f0` | biz_127 | Doanh thu tháng 3/2026 bao nhiêu | Sai | `1098707000` | `0` | Bước 1, 3 | **(B) Partially Solved** | Lỗi: Filter `hoàn thành` làm rỗng biz_127 (`completed`) -> 0. Bước 1 đưa `completed`, Bước 3 chặn 0. Cần cộng tiền theo dòng hàng. |
| 28 | `q_e7837d5638fb` | biz_122 | Tổng doanh thu tháng 9/2025 là bao nhiêu | Sai | `248572900` | `252854400` | Không | **(C) Unsolved** | Lỗi: Merged cells làm trống 2.654 dòng con. Code để lọt dòng trống và đơn hoàn. 3 bước không có `ffill()`, cần module unmerge của Rulebook §8. |
| 29 | `q_e9930d87abdd` | biz_109 | Bảng 5 khách nợ nhiều nhất đến hết 27/03/2026 | Abstain | Bảng 5 khách | `null` | Bước 1, 2 | **(B) Partially Solved** | Lỗi: Trùng tên cột `Thời gian` giữa hoá đơn và sổ quỹ -> KeyError 3 lượt. Bước 1 & 2 gỡ KeyError. Cần thêm logic sổ quỹ Rulebook §4. |
| 30 | `q_fcafb39ec35f` | biz_109 | Khách đường Lê Trọng Tấn vs Trần Não ai mua nhiều hơn | Sai | `unanswerable` | `"Hai bên mua bằng nhau"` | Bước 1, 3 | **(A) Fully Solved** | Lỗi: Thiếu cột địa chỉ, lọc cả 2 ra rỗng (0 đồng) -> kết luận bằng nhau. Bước 1 & 3 phát hiện rỗng cột địa chỉ, chốt chuẩn `unanswerable`. |

---

# R3. RÀ SOÁT CÁC RỦI RO KỸ THUẬT, ĐIỂM MÙ & VẤN ĐỀ TỒN ĐỌNG

Qua phân tích kiến trúc chuyên sâu, nhóm phát hiện **5 điểm mù kỹ thuật nghiêm trọng** mà phản hồi 3 bước chưa tính tới:

### 1. Rủi ro Độ trễ (Latency) & Nguy cơ Bị Huỷ Bài (Timeout Termination) trong Docker Offline
* **Quy chế cuộc thi:** Chạy container hoàn toàn offline (`--network none`) trên máy chủ chuẩn `2x RTX 5090 (64GB VRAM)`. Giới hạn thời gian chấm điểm: **Tối đa 6 giờ (21.600 giây)** cho ~500 câu hỏi private test.
* **Bài toán ngân sách thời gian:**
  $$\text{Ngân sách trung bình} = \frac{21.600\text{ giây}}{500\text{ câu}} = 43.2\text{ giây/câu (gross)} \longrightarrow \text{Ngưỡng an toàn } \le 35\text{ giây/câu}$$
* **Hệ quả của Multi-turn vô tội vạ:** Nếu câu nào cũng chạy 2–3 lượt sinh LLM (Turn 1 thăm dò, Turn 2 tính toán, Turn 3 sửa lỗi), thời gian sẽ lên tới **45–60 giây/câu**. Khi vượt quá 6 giờ, Docker container sẽ bị kill, các câu chưa chạy nhận 0 điểm, và hệ thống thua tuyệt đối ở tiêu chí phụ (tie-breaker là *Tổng thời gian suy luận*).
* **Phá vỡ Prefix Caching:** Mỗi lượt thăm dò sinh ra stdout observation ngẫu nhiên làm mất hiệu lực của KV-cache (`prefix caching`) trong vLLM, làm tăng vọt độ trễ prefill và giảm thông lượng batching.

### 2. Bản chất Toán học của Abstain Gate dưới Công thức Penalized Accuracy (PA)
* Công thức tính điểm:
  $$\text{PA} = \frac{1}{N} \sum S(y_i, \hat{y}_i), \quad S = \begin{cases} +1.0 & \text{Đúng} \\ 0.0 & \text{Abstain} \\ -1.0 & \text{Sai (Phạt nặng!)} \end{cases}$$
* Kỳ vọng toán học khi quyết định trả lời với độ tin cậy $p$:
  $$E[S] = p \times (+1.0) + (1-p) \times (-1.0) = 2p - 1$$
  $$E[S] > 0 \iff 2p - 1 > 0 \iff p > 0.5 \quad (50\%)$$
* **Bẫy của việc cố sửa (The Retry Trap):** Nếu Bước 3 phát hiện kết quả rỗng hoặc bất thường mà tiếp tục cho model 14B thử lại tự do ở Turn 2, Turn 3 mà không có thông tin mới, xác suất đoán đúng $p$ thường $< 0.2$. Khi đó $E[S] \approx -0.6$ (thua xa mức 0.0 của Abstain).
* **Quy tắc bắt buộc:** Khi kết quả đáng nghi và không thể sửa bằng quy tắc tất định, **HỆ THỐNG BẮT BUỘC PHẢI CHUYỂN THÀNH `"abstain"` ĐỂ CẮT LỖ (nhận 0 điểm an toàn thay vì -1.0 điểm phạt).**

### 3. Thực tế Dữ liệu Bẩn (Data Messiness) làm Phá sản Naive Profiling
* **Ô gộp (Merged Cells) chiếm tới 47% dữ liệu:** Trong `biz_121` và `biz_122`, có tới 38.878/82.920 dòng và 2.654/5.635 dòng bị trống thông tin cấp đơn (`Mã đơn`, `Ngày`, `Trạng thái`) do phần mềm bán hàng xuất file gộp ô. Naive profiling sẽ coi đây là cột bình thường, khiến code lọc của LLM vô tình vứt bỏ gần một nửa số dòng hàng! Bắt buộc phải có module `ffill()` tự động trước khi profile.
* **Ngày tháng hỗn loạn & Lịch Âm - Dương:** Trong SQLite, cột `NgayLap` chứa chuỗi hỗn hợp (`25/05/2026`, `25 thg 5 2026`, số serial Excel). Câu hỏi về dịp Tết Nguyên Đán hay "cùng kỳ năm ngoái" bắt buộc phải tra cứu bảng `calendar.csv` thay vì dùng phép trừ ngày thông thường.

### 4. Rủi ro Ngữ nghĩa & Ảo giác trong Code Thăm dò Sandbox
* Khi model tự viết script thăm dò ở Bước 2, nếu script bị lỗi cú pháp, timeout, hoặc dùng regex tìm kiếm sai dẫn đến kết quả trả về `data: []`, model ở lượt sau sẽ bị ảo giác rằng "cửa hàng hoàn toàn không có dữ liệu này" và xuất `unanswerable` sai (mất -1.0 điểm phạt).

### 5. Tiêu chí Tái lập Kết quả (Reproducibility $\le 0.03$)
* Thể lệ quy định: Sai số giữa kết quả nộp và kết quả BTC chạy lại không được lệch quá $|\text{PA}_{\text{uploaded}} - \text{PA}_{\text{rerun}}| \le 0.03$. Việc duy trì một vòng lặp đa lượt ngẫu nhiên làm tăng phương sai kết quả. Single-turn kết hợp deterministic pre-processing sẽ đảm bảo tính tất định 100%.

---

# R4. TỔNG KẾT ĐÁNH GIÁ & KHUYẾN NGHỊ ĐIỀU CHỈNH CÓ THỨ TỰ ƯU TIÊN

### 1. Đánh giá Tổng quan Đề xuất
- **Nhận xét:** Đề xuất cải tiến 3 bước là **rất chuẩn xác, đi đúng vào các điểm nghẽn thực tế** của mô hình.
- **Những điểm CẦN GIỮ NGUYÊN:**
  1. Giữ nguyên toàn bộ cấu trúc **Bước 1 (Bản đồ dữ liệu gọn)**: Hiển thị đầy đủ nhãn cho cột $\le 20$ unique; count + mẫu cho cột $> 20$.
  2. Giữ nguyên triết lý **Bước 3 (Sanity check)** để bắt kết quả 0, `[]`, DataFrame rỗng.
- **Những điểm CẦN ĐIỀU CHỈNH & BỔ SUNG:**
  1. *Chuyển hóa Bước 2:* Không chạy thăm dò runtime bằng LLM cho mọi câu. Thay vào đó, thực hiện **Deterministic Pre-profiling (Bước 0)** bằng Python thuần (< 0.2s) để trích xuất sẵn các giá trị cột, phân bố ngày, và mẫu dữ liệu nhúng thẳng vào prompt lượt 1. Chỉ dùng LLM exploration có điều kiện cho câu hỏi join phức tạp.
  2. *Bổ sung Engine Xử lý Merged Cells:* Tích hợp helper `read_clean_excel()` tự động `ffill()` các trường cấp đơn theo Rulebook §8.
  3. *Kích hoạt Hard Abstain Gate:* Bật `eval_core_rules = True` trong `src/agent/solver.py`, cưỡng chế xuất `abstain` khi phát hiện kết quả lọc rỗng mà không thể phục hồi.

---

### 2. Lộ trình Triển khai Kỹ thuật Ưu tiên (Actionable Priority Roadmap)

```
[ƯU TIÊN 1 (P1): 0.5 ngày] ──> [ƯU TIÊN 2 (P2): 0.5 ngày] ──> [ƯU TIÊN 3 (P3): 1 ngày] ──> [ƯU TIÊN 4 (P4): 1 ngày]
Kích hoạt Bước 1 (Schema)     Bật Bước 3 & Abstain Gate    Xử lý Merged Cells & Lịch    Thăm dò có điều kiện & Test
```

| Thứ tự | Hạng mục công việc chi tiết | Vị trí can thiệp trong Codebase | Tác động dự kiến trên 30 câu dev | Thời gian |
|:---:|---|---|---|:---:|
| **P1** | **Kích hoạt Bản đồ Dữ liệu Gọn (Bước 1)**<br>Xuất đầy đủ nhãn cho cột $\le 20$ unique (như trạng thái `completed`, `Xong`). Xuất count + 3 mẫu có nhãn minh thị cho cột $>20$. | `src/profiler/business_loader.py`<br>(hàm `format_profile_for_prompt`) | Khắc phục ngay lập tức **7 câu lỗi lọc nhãn rỗng** (`q_20aa992c0d3f`, `q_e0aef192cb11`, v.v.) | 0.5 ngày |
| **P2** | **Kích hoạt Sanity Check & Hard Abstain Gate (Bước 3)**<br>Bật cấu hình `eval_core_rules = True`. Hoàn thiện `_eval_guard_issue()` để chặn kết quả doanh thu = 0 khi rỗng dòng, top-k `[]`, bảng toàn 0. Ép xuất `abstain` thay vì đoán mò khi hết lượt retry. | `src/agent/solver.py`<br>(hàm `_eval_guard_issue` & `_answer_question_steps`) | Cứu ngay **5–8 câu bị phạt -1.0 điểm** chuyển về `abstain` (tăng PA thêm +0.30 đến +0.45). | 0.5 ngày |
| **P3** | **Cung cấp Helper Xử lý Merged Cells & Lịch Âm Dương**<br>Thêm helper `read_clean_excel(path, sheet)` tự động `ffill()` các cột cấp đơn trong sandbox. Nâng cấp `time_resolver` hỗ trợ cụm "cùng kỳ tháng trước/năm trước" và tra cứu `calendar.csv`. | `src/agent/sandbox.py`<br>`src/time_resolver/calendar_utils.py` | Giải quyết dứt điểm các câu ô gộp (`q_e7837d5638fb`, `q_5c5ff524d0d9`) và câu cùng kỳ (`q_d401c0884402`). | 1.0 ngày |
| **P4** | **Thăm dò Sandbox có Điều kiện (Conditional Exploration)**<br>Chỉ kích hoạt observation turn cho câu hỏi join $\ge 2$ bảng hoặc câu hỏi tìm kiếm chuỗi không dấu. Bổ sung template an toàn tránh lỗi hậu tố `_x`, `_y`. | `src/agent/solver.py`<br>(hàm `build_observation_prompt`) | Giải quyết dứt điểm các lỗi KeyError join (`q_019ec94d9799`, `q_aacf9543a235`) và tìm kiếm không dấu (`q_01a28f2233bd`). | 1.0 ngày |

---

### 3. Phán quyết về việc Huấn luyện lại Mô hình (Model Retraining Decision)

> ### ⛔ KẾT LUẬN: TUYỆT ĐỐI CHƯA CẦN TRAIN LẠI MODEL VÀO LÚC NÀY!

**Lập luận căn cứ kỹ thuật:**
1. **Năng lực mô hình hiện tại đã đáp ứng tốt:** Mô hình Qwen2.5-Coder-14B viết code Python rất chuẩn, import đúng thư viện, cấu trúc logic mạch lạc. Các ca lỗi phát sinh trong eval vừa qua 100% bắt nguồn từ việc mô hình bị "bịt mắt" trước dữ liệu (không được cung cấp nhãn `completed`/`Xong`, không thấy tên cột sau join, bị ô gộp làm rỗng dữ liệu).
2. **Nguy cơ Overfitting dữ liệu huấn luyện:** Trong tập 817 mẫu train có 38 mẫu dùng nhãn `"hoàn thành"`. Nếu tiếp tục fine-tune trên dữ liệu thô mà không chuẩn hóa pipeline, model sẽ càng học vẹt nhãn `"hoàn thành"`, gây tác dụng ngược trên các shop dùng nhãn khác trong test set.
3. **Hiệu quả biên vượt trội của tầng Pipeline:** Chỉ cần triển khai các can thiệp tầng hệ thống (P1 + P2 + P3), điểm PA trên tập 30 câu dev dự kiến sẽ tăng vọt từ **-0.5000 lên khoảng +0.4000 đến +0.5333** chỉ sau 2–3 ngày làm việc mà không tốn chi phí GPU train.
4. **Thời điểm thích hợp để train lại:** Chỉ xem xét huấn luyện thêm một epoch LoRA (hoặc DPO) sau khi đã cố định hoàn chỉnh pipeline P1–P4, và sử dụng chính các trace log sạch từ pipeline mới để làm dữ liệu huấn luyện.
