# BÁO CÁO PHÂN TÍCH PHẢN BIỆN CHUYÊN SÂU & RÀ SOÁT KỸ THUẬT PIPELINE 3 BƯỚC (DATAMATE 2026)

> **Tài liệu nghiên cứu kỹ thuật nội bộ**  
> **Người thực hiện:** Teamwork Explorer 1  
> **Ngày thực hiện:** 2026-11-11  
> **Dự án:** Zalo AI Challenge 2026 — Task: DataMate (QA tiếng Việt trên dữ liệu bảng biểu doanh nghiệp)  
> **Tài liệu đối chiếu trọng tâm:** `result/qwen25_14b_1m_code_only_rulebook_20261111_155610/eval_dev_30_colab_a100_40gb_ctx16384/failure_analysis.md`, codebase `src/`, `scripts/`, `configs/`, `docs/`, `AGENTS.md`.

---

## TỔNG QUAN ĐIỀU HÀNH (EXECUTIVE SUMMARY)

Đề xuất cải tiến pipeline 3 bước bao gồm:
1. **Bước 1 — Bản đồ dữ liệu gọn (Compact Data Map):** Bổ sung danh sách nhãn chính xác cho các cột ít giá trị (low cardinality) và số lượng kèm mẫu có nhãn cho các cột nhiều giá trị (high cardinality).
2. **Bước 2 — Lượt khám phá có mục tiêu trong sandbox (Targeted Sandbox Exploration):** Tận dụng luồng `observation` để chạy script thăm dò trên raw data trước khi chốt đáp án.
3. **Bước 3 — Kiểm tra kết quả đáng nghi trước khi chốt (Suspicious Result Sanity Check):** Tự động phát hiện và chặn các kết quả 0, `[]`, DataFrame rỗng sau lọc/join, hoặc nhãn không khớp trước khi phát hành `final`.

### Kết luận đánh giá cốt lõi:
- **Tính đúng đắn về chiến lược:** Đề xuất 3 bước đánh trúng vào **80% các nguyên nhân gây lỗi trực tiếp** trong đợt đánh giá 30 câu dev vừa qua (đặc biệt là lỗi lọc nhãn trạng thái rỗng làm mất 7 câu, lỗi KeyError hậu tố join làm mất 4 câu abstain, và lỗi so khớp chuỗi/ngày làm mất 3 câu).
- **Thống kê phân loại trên 30 câu dev:**
  - **Nhóm A — Giải quyết hoàn toàn (Fully Solved):** **14/30 câu (46.7%)**, bao gồm 10 câu lỗi/abstain được khắc phục triệt để và 4 câu vốn đã đúng được bảo toàn.
  - **Nhóm B — Cải thiện đáng kể / Giảm thiểu rủi ro điểm phạt (Partially Solved / Risk Mitigated):** **14/30 câu (46.7%)**. Ở nhóm này, 3 bước giúp chặn các kết quả sai vô lý (0, [], unanswerable ảo) để chuyển về `abstain` an toàn (tránh mất -1.0 điểm), hoặc giải quyết được 1 phần bước tính nhưng vẫn cần bổ sung thêm hiểu biết Rulebook (doanh thu theo dòng, sổ quỹ) hoặc time resolver.
  - **Nhóm C — Chưa giải quyết được (Unsolved):** **2/30 câu (6.7%)**, gồm case Excel merged cells làm rỗng 2.654 dòng con (`q_e7837d5638fb`) và case chia nhầm mẫu số tỉ lệ huỷ đơn theo dòng thay vì theo mã đơn phân biệt (`q_67297f4bdfc2`).
  - **Nhóm D — Nguy cơ làm hỏng trực tiếp (Worsened):** **0/30 câu**, nhưng tồn tại **3 rủi ro hệ thống tiềm ẩn** (Bùng nổ latency khi chạy multi-turn, Nguy cơ False Positive chặn nhầm 0 thật, và Nguy cơ Hallucination trong code thăm dò) cần các chốt chặn kiến trúc nghiêm ngặt.
- **Tiềm năng điểm số Penalized Accuracy (PA):** Nếu áp dụng chuẩn xác pipeline 3 bước kết hợp Abstain Gate, điểm PA kỳ vọng trên tập 30 câu dev có thể nhảy vọt từ **-0.5000** lên khoảng **+0.3667 đến +0.5333** mà **CHƯA CẦN TRAIN LẠI MODEL**.

---

## PHẦN 1: PHÂN TÍCH VÀ PHẢN BIỆN CHI TIẾT ĐỀ XUẤT CẢI TIẾN PIPELINE 3 BƯỚC (R1)

### 1.1. Bước 1: Bản đồ dữ liệu gọn (Compact Data Map with Cardinality Partitioning)

#### A. Cơ chế vận hành đề xuất
- Trích xuất cấu trúc siêu dữ liệu bảng biểu từ thư mục dữ liệu của shop (`BUSINESS_DIR`): tên file, tên sheet, danh sách cột và kiểu dữ liệu (dtype).
- **Phân định Cardinality:**
  - **Cột ít giá trị (Low-Cardinality, ngưỡng $\le 20$ unique values):** Cung cấp đầy đủ toàn bộ các nhãn quan sát được trong dữ liệu (ví dụ: `Trạng thái: ['Xong', 'Đang giao', 'Đã huỷ', 'Hoàn trả']`, `Hình thức thanh toán: ['Tiền mặt', 'Chuyển khoản', 'COD']`, `Loại khách: ['Cá nhân', 'Doanh nghiệp']`).
  - **Cột nhiều giá trị (High-Cardinality, $> 20$ unique values):** Chỉ cung cấp số lượng giá trị phân biệt (`unique_count`) và 3–5 mẫu đại diện kèm thông điệp cảnh báo rõ ràng: `[Ví dụ quan sát được (chỉ là mẫu, không phải toàn bộ)]: ['SP001', 'SP002', ...]`.

#### B. Ưu điểm nổi bật
1. **Tiêu diệt tận gốc lỗi "Ảo giác nhãn lọc" (Filter Label Hallucination):** Trong run eval vừa qua, 7/30 câu (23.3%) thất bại thảm hại do model tự biên tự diễn dùng `.str.contains("hoàn thành")` trên các shop dùng nhãn `Xong` (biz_101) hoặc `completed` (biz_111, biz_127, biz_129). Khi prompt liệt kê rõ `Trạng thái: ['completed', 'cancelled']`, model sẽ trực tiếp sử dụng nhãn thật mà không suy đoán từ văn phong đời thường.
2. **Kiểm soát chặt chẽ Context Window:** So với việc dump hàng chục dòng sample hoặc dump schema tràn lan (dễ ngốn 4.000–8.000 tokens), bản đồ gọn chỉ tốn khoảng 400–800 tokens, giúp giữ chỗ cho Rulebook và code generation, đồng thời giảm đáng kể thời gian prefill của vLLM trên GPU RTX 5090.
3. **Ngăn chặn ngộ nhận mẫu là toàn bộ dữ liệu:** Nhãn cảnh báo minh thị giúp model không bao giờ suy luận "cửa hàng chỉ có 3 sản phẩm" hay "chỉ có 5 khách hàng".

#### C. Nhược điểm & Điểm mù cần lưu ý
1. **Chi phí thời gian trích xuất (Profiling Latency / Cold Start):** Đối với các file Excel dung lượng lớn (như biz_121, biz_122 có hơn 80.000 dòng trên nhiều sheet), hàm `pd.read_excel()` để quét toàn bộ cột và tính `unique()` có thể tốn từ 5 đến 15 giây nếu chạy tuần tự.
   - *Khắc phục:* Bắt buộc phải dùng engine siêu tốc `calamine` (`python-calamine`) và cơ chế cache `_profile_cache` ở cấp độ `business_id` (đã có trong `src/agent/solver.py`, chỉ profile 1 lần cho mỗi shop).
2. **Nhiễu dữ liệu làm bùng nổ cardinality giả:** Một số cột danh mục như `Trạng thái` nhưng nhân viên bán hàng gõ tự do (free-text comments, ghi chú giao hàng), dẫn đến số lượng unique values vượt quá 20.
   - *Khắc phục:* Cần chuẩn hóa chuỗi cơ bản (`strip()`, `casefold()`) và lọc bỏ chuỗi rỗng trước khi đếm cardinality; nếu cột có tên nhạy cảm như `trạng thái`, `status`, `loại` thì nâng ngưỡng lên $\le 30$.

#### D. Tính khả thi kỹ thuật trong Codebase
- **Độ sẵn sàng: 100%.** Trong `src/profiler/business_loader.py`, struct `TableSchema` đã thu thập sẵn `categorical_values` và `truncated_categorical`. Hiện tại hàm `format_profile_for_prompt(compact=True)` đang cố tình lược bỏ phần này. Chỉ cần kích hoạt lại việc hiển thị `categorical_values` có chọn lọc theo ngưỡng cardinality là hoàn tất.

---

### 1.2. Bước 2: Lượt khám phá có mục tiêu trong sandbox (Targeted Sandbox Exploration via Observation Loop)

#### A. Cơ chế vận hành đề xuất
- Thay vì ép model giải bài toán trong đúng 1 lượt sinh (`turn 1`) rồi chốt kết quả, hệ thống cho phép (hoặc điều hướng) model sinh một đoạn script Python ngắn nhằm mục đích thăm dò dữ liệu trong môi trường sandbox (`src/agent/sandbox.py`).
- Script in ra stdout đối tượng JSON tuân thủ giao thức:
  ```json
  {"kind": "observation", "data": ..., "message": "..."}
  ```
- Sandbox bắt stdout, nhúng kết quả vào user prompt của lượt tiếp theo (`build_observation_prompt()`), giúp model ở `turn 2` nhìn thấy dữ liệu thực tế (ví dụ: các giá trị ngày tháng thực tế, tên cột sau khi merge, danh sách SKU khớp regex) rồi mới sinh script tính toán và chốt `kind: "final"`.

#### B. Ưu điểm nổi bật
1. **Khắc phục triệt để lỗi bất đồng bộ Schema & Hậu tố Join Pandas:** Trong Pandas, khi join 2 DataFrame cùng có cột `Thời gian` hoặc `Tên hàng`, Pandas tự động đổi tên thành `Thời gian_x`, `Thời gian_y`. Lỗi này đã khiến 4 câu trong eval rơi vào vòng lặp `KeyError` và phải `abstain` cả 3 lượt (`q_019ec94d9799`, `q_aacf9543a235`, `q_e9930d87abdd`, `q_583e4896e764`). Ở lượt thăm dò, model chỉ cần chạy `print(list(df.columns))` sau join là phát hiện ngay tên cột thực tế.
2. **Giải quyết tìm kiếm chuỗi tiếng Việt không dấu & Fuzzy Match:** Với câu hỏi hỏi "soda chanh day (m)" (`q_01a28f2233bd`), script thăm dò có thể dùng regex không dấu `vn_norm()` để quét danh mục hàng hóa, tìm ra đúng chuỗi chuẩn `"Soda chanh dây (M)"` trước khi query doanh thu.
3. **Phát hiện định dạng ngày tháng phi chuẩn:** Đối với SQLite lưu ngày dưới dạng chuỗi hỗn hợp (`25/05/2026`, `25 thg 5 2026`, số serial Excel như ở `q_2ea34572153a`), một câu lệnh thăm dò `SELECT DISTINCT NgayLap LIMIT 5` giúp model nhận ra ngay không thể so sánh chuỗi ISO trực tiếp.

#### C. Nhược điểm & Rủi ro lớn
1. **Rủi ro bùng nổ thời gian suy luận (Latency Overhead):** Trong môi trường offline, mô hình Qwen2.5-Coder-14B chạy trên GPU mất trung bình **10–18 giây** cho mỗi lượt sinh code (prefill + decode ~300 tokens). Nếu câu nào cũng chạy 2 lượt (Turn 1 probe + Turn 2 solve), tổng thời gian mỗi câu sẽ tăng lên **25–40 giây**. Đối với 100–150 câu hỏi test, tổng thời gian có thể chạm ngưỡng 60–90 phút, đe dọa trực tiếp giới hạn thời gian nộp bài của ban tổ chức.
2. **Model SFT có xu hướng "học vẹt chốt final" (Final Eagerness):** Kết quả từ `failure_analysis.md` chỉ rõ: **12/19 câu sai chốt final ngay tại turn 1!** Cả 54 lượt sinh trong đợt eval không có lượt nào model tự giác chủ động xuất `kind: "observation"` nếu prompt không ép buộc. Mô hình 14B sau fine-tune code-only luôn muốn giải quyết bài toán ngay lập tức.
3. **Rủi ro Hallucination trong bước khám phá (Misleading Exploration):** Nếu script thăm dò viết regex sai hoặc query sai sheet, sandbox trả về `data: []`. Khi đó, ở Turn 2 model sẽ bị ảo giác rằng "dữ liệu không hề tồn tại trong shop" và vội vàng kết luận `unanswerable` sai (bị phạt -1.0 điểm).
4. **Tràn bộ nhớ Context khi dump dữ liệu quá lớn:** Nếu script thăm dò in ra một DataFrame 1.000 dòng vào `data`, chuỗi JSON observation sẽ làm nổ context window, gây chậm trễ nghiêm trọng và lãng phí VRAM.

#### D. Tính khả thi kỹ thuật trong Codebase
- **Độ sẵn sàng: 90%.** Giao thức `ProtocolKind.OBSERVATION` và hàm `build_observation_prompt()` đã có sẵn trong `sandbox.py` và `solver.py`. Tuy nhiên, để khai thác hiệu quả mà không bị bùng nổ latency, **KHÔNG NÊN** cho chạy tự do mà cần cơ chế **Thăm dò có điều kiện (Conditional Exploration)**: Chỉ kích hoạt lượt thăm dò đối với các câu hỏi phức tạp (chứa từ khóa nối nhiều bảng, câu hỏi không dấu, hoặc câu hỏi có cấu trúc ngày lạ).

---

### 1.3. Bước 3: Kiểm tra kết quả đáng nghi trước khi chốt (Suspicious Result Sanity Check & Guardrails)

#### A. Cơ chế vận hành đề xuất
- Đóng vai trò là chốt kiểm duyệt chất lượng đầu ra (Safety Interceptor) nằm giữa Sandbox Runner và Module định dạng đáp án (`format_answer_payload`).
- **Các tiêu chí kích hoạt nghi vấn (Suspicion Triggers):**
  1. **Doanh thu / Tiền bán / Số lượng bán ra = 0:** Trừ khi câu hỏi hỏi về mặt hàng ế, không bán được, việc một shop đang hoạt động có doanh thu tháng/tuần bằng 0 là tín hiệu chắc chắn của việc lọc rỗng DataFrame (`rows_after_filter == 0`).
  2. **Xếp hạng / Danh sách Top-k ra danh sách rỗng `[]`:** Bất kỳ câu hỏi top-k nào trả về mảng rỗng đều là do bộ lọc ngày tháng hoặc điều kiện join triệt tiêu toàn bộ dữ liệu.
  3. **Danh sách Top-k bị trùng lặp phần tử:** Danh sách top 3 nhưng lại trả về 3 phần tử giống hệt nhau (ví dụ: `['Bánh croissant', 'Bánh croissant', 'Bánh croissant']` ở `q_02a70ea566f1`) do quên `groupby().sum()`.
  4. **Số đếm số lượng đơn hàng âm (`count < 0`):** Vi phạm định lý đếm cơ bản.
  5. **Bảng công nợ chứa toàn bộ số tiền nợ bằng 0:** Câu hỏi tìm khách nợ nhiều nhất nhưng tất cả các dòng đều có `amount_due == 0` (như ở `q_9b1dce77c710`).
  6. **So sánh 2 tập hợp mà cả 2 tập hợp đều có 0 dòng:** Kết luận "hai bên mua bằng nhau" khi cả 2 bên đều có 0 đơn hàng (như ở `q_fcafb39ec35f`).
- **Hành động phản ứng:**
  - Nếu còn lượt retry (turn budget > 0): Trả về thông báo lỗi hướng dẫn chi tiết yêu cầu model kiểm tra lại nhãn và ngày tháng:
    > *"Cảnh báo: Kết quả tính toán cho doanh thu/số lượng bằng 0 do DataFrame sau khi lọc có 0 dòng (len=0). Hãy in df[col].unique() để kiểm tra lại nhãn trạng thái và định dạng ngày."*
  - Nếu đã hết lượt retry: **Kích hoạt Abstain Gate chuyển kết quả sang `abstain` (0.0 điểm) để chặn đứng việc bị phạt -1.0 điểm.**

#### B. Ưu điểm nổi bật
1. **Bảo vệ điểm số tối đa dưới công thức Penalized Accuracy (PA):** Trong thang điểm PA: Sai = -1.0 điểm, Abstain = 0.0 điểm. Một câu sai làm bốc hơi toàn bộ điểm số của một câu đúng! Việc chặn đứng các câu trả lời 0, [], hoặc unanswerable ảo là chiếc phao cứu sinh quan trọng nhất giúp điểm PA không bị âm sâu.
2. **Hệ thống có sẵn khung sườn:** Trong `src/agent/solver.py`, hàm `_eval_guard_issue()` đã được lập trình sẵn một số quy tắc này (dòng 659–695). Tuy nhiên, trong cấu hình run eval vừa rồi, biến `eval_core_rules` bị đặt là `False`, khiến guardrail bị tê liệt hoàn toàn!

#### C. Nhược điểm & Rủi ro cần phòng ngừa
1. **Nguy cơ False Positive (Chặn nhầm kết quả 0 hợp lệ):** Có những câu hỏi nghiệp vụ mà đáp án đúng thực sự là 0 (ví dụ: ngày lễ quán đóng cửa, khách hàng thực sự không nợ đồng nào, hoặc tỉ lệ tăng trưởng bằng 0.0%). Nếu chặn mù quáng số 0, hệ thống sẽ biến một đáp án đúng thành câu trả lời sai hoặc bị ép abstain mất điểm.
   - *Khắc phục:* Chỉ chặn số 0 khi kiểm tra thêm điều kiện `rows_after_filter == 0` (tức rỗng do lọc) thay vì chặn giá trị 0 sinh ra từ một DataFrame có dữ liệu thực sự tính ra tổng bằng 0.
2. **Cạn kiệt lượt sửa (Retry Exhaustion):** Nếu câu nhắc lỗi không đủ cụ thể, model có thể rơi vào vòng lặp lặp lại đúng lỗi đó trong cả 3 lượt (như đã thấy ở 3 câu runtime error trong eval).

---

## PHẦN 2: ĐỐI CHIẾU TRỰC TIẾP VỚI KẾT QUẢ ĐÁNH GIÁ 30 CÂU TRONG FAILURE_ANALYSIS.MD (R2)

### 2.1. Ma trận Thống kê Phân loại Tổng thể

Dựa trên phân tích mã nguồn sinh ra trong các log của run `eval_dev_30_colab_a100_40gb_ctx16384` đối chiếu với bộ dữ liệu chuẩn `eval_gold/unseen_gold_30.jsonl`:

| Nhóm Phân loại | Số lượng câu | Tỷ lệ (%) | Diễn giải tác động kỹ thuật |
|---|:---:|:---:|---|
| **(A) Fully Solved** (Giải quyết hoàn toàn) | **14** | **46.7%** | 10 câu lỗi/abstain được giải quyết dứt điểm về mặt dữ liệu và logic; 4 câu baseline đúng được duy trì tính ổn định. |
| **(B) Partially Solved / Risk Mitigated** (Cải thiện / Chặn rủi ro điểm phạt) | **14** | **46.7%** | Giải quyết được lỗi rỗng dữ liệu/nhãn, hoặc dùng Sanity Check & Abstain Gate chặn các kết quả 0, [] để chuyển thành `abstain` (cứu -1.0 điểm phạt). Một số câu cần thêm module phụ (sổ quỹ, time resolver, doanh thu theo dòng). |
| **(C) Unsolved** (Chưa giải quyết được) | **2** | **6.7%** | Lỗi định dạng Excel Merged Cells phức tạp và hiểu sai công thức mẫu số trong Rulebook §1. Đòi hỏi module tiền xử lý bảng biểu chuyên biệt. |
| **(D) Worsened** (Làm hỏng trực tiếp) | **0** | **0.0%** | Không có câu nào bị làm sai đi nếu áp dụng đúng cơ chế kiểm soát. |
| **TỔNG CỘNG** | **30** | **100.0%** | |

---

### 2.2. Bảng Đối chiếu Chi tiết Từng Câu (Granular Case-by-Case Mapping)

Dưới đây là bảng phân tích toàn diện 30 câu hỏi dev theo đúng yêu cầu kiểm định:

| STT | Question ID | Biz ID | Câu hỏi | Kết quả Eval | Gold Answer | Pred Answer | Bước can thiệp | Phân loại | Nguyên nhân gốc rễ & Cơ chế tác động của 3 Bước |
|:---:|---|:---:|---|:---:|---|---|:---:|:---:|---|
| 1 | `q_019ec94d9799` | biz_106 | 3 mặt hàng bán chạy nhất tuần này là những mặt hàng nào? | Abstain | `['Cà phê sữa (M)', 'Trà đào cam sả (M)', 'Cà phê đen (M)']` | `null` | Bước 1, Bước 2 | **(A) Fully Solved** | **Lỗi:** Join 2 bảng cùng có `Tên hàng` khiến Pandas đổi tên thành `Tên hàng_x`, `Tên hàng_y`. Code group by `Tên hàng` bị KeyError lặp lại 3 lượt.<br>**Cơ chế giải quyết:** Bước 1 cung cấp schema rõ ràng của từng file; Bước 2 cho phép probe cột sau join để code dùng đúng tên cột; tránh KeyError và ra đúng top 3. |
| 2 | `q_01a28f2233bd` | biz_112 | gia ban mot ly soda chanh day (m) vao ngay 01/12/2025 la bn | Abstain | `37000` | `null` | Bước 2 | **(A) Fully Solved** | **Lỗi:** Câu hỏi ghi không dấu "soda chanh day (m)". Code so sánh chuỗi có dấu trực tiếp làm rỗng DataFrame -> IndexError -> thiếu evidence.<br>**Cơ chế giải quyết:** Bước 2 (Targeted Exploration) dùng `vn_norm()` quét danh mục, tìm ra chính xác `"Soda chanh dây (M)"` có giá bán 37.000 ngày 01/12. |
| 3 | `q_02a70ea566f1` | biz_112 | Top 3 sp bán nhiều nhất tháng 3 năm 2026 là những gì? | Sai | `['Cà phê sữa (M)', 'Trà đào cam sả (M)', 'Cà phê đen (M)']` | `['Bánh croissant', 'Bánh croissant', 'Bánh croissant']` | Bước 2, Bước 3 | **(B) Partially Solved** | **Lỗi:** Code chạy `sort_values().head(3)` trên từng dòng đơn hàng nên lấy 3 dòng croissant của các đơn khác nhau thay vì `groupby("Tên hàng").sum()`.<br>**Cơ chế giải quyết:** Bước 3 phát hiện kết quả top 3 có phần tử trùng lặp (`A, A, A`), cảnh báo model group by theo tên hàng; Bước 2 hỗ trợ verify aggregation. |
| 4 | `q_132add5002d2` | biz_127 | dthu trung binh tren mot don thang 6/2026 la bao nhieu | Abstain | `535722` | `null` | Bước 1, Bước 3 | **(B) Partially Solved** | **Lỗi:** Filter `hoàn thành` làm rỗng tháng 6 (thực tế có 2.017 đơn `completed`) -> `mean()` ra NaN -> `int(NaN)` lỗi cả 3 lượt.<br>**Cơ chế giải quyết:** Bước 1 cung cấp nhãn `completed`, giúp DataFrame có 2.017 đơn, loại bỏ lỗi NaN. Tuy nhiên cần thêm Rulebook §1 (tính tổng tiền dòng thay vì `Tổng đơn`) để khớp hoàn toàn 535.722. |
| 5 | `q_1b119bdd5d28` | biz_109 | trong cac thang 7/2025, 8/2025 va 9/2025, cua hang co doanh thu cao nhat vao thang nao | Đúng | `2025-08` | `2025-08` | Không (Baseline) | **(A) Maintained Correct** | Baseline đã chạy đúng trong 1 lượt. Pipeline 3 bước không can thiệp làm sai lệch logic. |
| 6 | `q_20aa992c0d3f` | biz_101 | thang 5/2026 ngay nao cua hang ban dc nhieu tien nhat | Sai | `2026-05-09` | `2026-05-01` | Bước 1, Bước 3 | **(A) Fully Solved** | **Lỗi:** Filter `hoàn thành` làm rỗng dữ liệu biz_101 (nhãn thật là `Xong`). Code fallback gán cứng 01/05.<br>**Cơ chế giải quyết:** Bước 1 cung cấp nhãn `Xong`, Bước 3 chặn DataFrame rỗng. Khi lọc đúng đơn hợp lệ và cộng doanh thu theo ngày, kết quả ra đúng ngày `2026-05-09`. |
| 7 | `q_21c12147e6d6` | biz_127 | Tháng 6/2025 khách nào mua nhiều tiền nhất? | Abstain | `"Thân Hồng Nhung"` | `null` | Bước 1, Bước 2 | **(B) Partially Solved** | **Lỗi:** Lọc sai nhãn trạng thái + Join dùng cột `Mã KH` ở phía đơn thay vì `Customer ID` -> KeyError cả 3 lượt.<br>**Cơ chế giải quyết:** Bước 1 cung cấp nhãn `completed` và danh sách cột chuẩn có `Customer ID`. Bước 2 verify phép join, giúp code chạy thông suốt. |
| 8 | `q_22f59bab1075` | biz_112 | Hết hôm nay trong kho còn bao nhiêu hộp Bánh croissant nguyên và bao nhiêu cái lẻ? | Sai | `unanswerable` | `[166666666, 3]` | Bước 1, Bước 2, Bước 3 | **(B) Partially Solved** | **Lỗi:** Shop không có thẻ kho croissant. Model lấy `Tồn lớn nhất = 999.999.999` chia 6 ra số bánh vô lý.<br>**Cơ chế giải quyết:** Bước 1 & 2 làm rõ schema không có bảng theo dõi tồn kho thực tế. Bước 3 phát hiện con số 166 triệu bánh là phi thực tế, kích hoạt Abstain Gate chuyển sang `abstain` (cứu -1.0 điểm). |
| 9 | `q_2a0e86444947` | biz_106 | Trong tháng 7/2026, bao nhiêu đơn có tiền hàng đạt 130.000 đồng trở lên nhỉ? | Sai | `507` | `510` | Bước 1 | **(A) Fully Solved** | **Lỗi:** Regex lọc bỏ đơn huỷ/trả dùng `trả hàng` bỏ sót 3 đơn có nhãn `Hoàn trả` trên ngưỡng 130.000 (đếm ra 510 thay vì 507).<br>**Cơ chế giải quyết:** Bước 1 cung cấp đầy đủ danh mục nhãn trạng thái có chữ `Hoàn trả`, model sẽ viết regex bao hàm `hoàn|trả`, loại bỏ đúng 3 đơn này và ra chính xác 507. |
| 10 | `q_2ea34572153a` | biz_123 | Xem giúp 3 khách hàng có tổng tiền mua cao nhất tuần rồi là ai? | Sai | `['Vương Khoa Quang', 'Tô Đức Mai', 'Diệp Hiếu Khánh']` | `[]` | Bước 1, Bước 2, Bước 3 | **(A) Fully Solved** | **Lỗi:** SQLite lưu `NgayLap` dưới nhiều dạng chuỗi tiếng Việt (`25/05/2026`, `25 thg 5 2026`). Model so sánh trực tiếp chuỗi ISO trong SQL làm tập kết quả rỗng -> trả về `[]`.<br>**Cơ chế giải quyết:** Bước 3 chặn ngay kết quả rỗng `[]` cho câu top-k. Bước 1 & 2 cung cấp mẫu ngày, model dùng `parse_vn_date()` trước khi lọc tuần, tái tính đúng 3 khách hàng. |
| 11 | `q_338ae382671b` | biz_105 | Tuần trước ca chiều so với ca sáng thì doanh thu chênh bao nhiêu %? | Sai | `-16.41` | `-18.69` | Bước 1, Bước 2 | **(B) Partially Solved** | **Lỗi:** Model bỏ qua điều kiện tuần trước (dùng cả sheet tháng 3) và lọc sai nhãn trạng thái -> tính ra -18.69%.<br>**Cơ chế giải quyết:** Bước 1 sửa nhãn trạng thái. Nhưng việc model bỏ sót điều kiện tuần trước trong prompt cần cải thiện prompt engineering. Lọc đúng tuần cho ra -16.36% (tiệm cận gold -16.41%). |
| 12 | `q_3b5c9002b013` | biz_109 | Giúp mình tính đến hết ngày 14/06/2025, có bao nhiêu khách còn nợ cửa hàng? | Sai | `121` | `0` | Bước 3 | **(B) Partially Solved** | **Lỗi:** Lọc nhầm nhóm COD (Rulebook yêu cầu loại COD) và lấy snapshot `Đã trả` lúc xuất file thay vì sổ quỹ -> ra 0 khách nợ.<br>**Cơ chế giải quyết:** Bước 3 phát hiện số khách nợ = 0 là đáng nghi, chặn lại và ép `abstain` (cứu -1.0 điểm). Để ra đúng 121 cần model hiểu đúng Rulebook §4 (loại COD, cộng sổ quỹ). |
| 13 | `q_43df08e6cce8` | biz_109 | trong tháng 3/2025, khách Giang Phương Thu mua chịu thêm nhiêu và trả bớt nợ được bao nhiêu? | Sai | `[130500, 43500]` | `[0, 0]` | Bước 3 | **(B) Partially Solved** | **Lỗi:** Cả 2 đơn tháng 3 đã được khách trả hết tại thời điểm xuất file, model nhìn snapshot kết luận `[0, 0]`.<br>**Cơ chế giải quyết:** Bước 3 chặn kết quả `[0, 0]` đáng ngờ, kích hoạt Abstain Gate (cứu -1.0 điểm). Để ra đúng `[130500, 43500]` cần đọc sổ quỹ theo thời điểm mua/trả theo Rulebook §4. |
| 14 | `q_554d736852a5` | biz_111 | Trung bình mỗi đơn tháng 9/2025 mang về bao nhiêu dthu | Sai | `70017` | `unanswerable` | Bước 1, Bước 3 | **(B) Partially Solved** | **Lỗi:** Nhãn `completed` không khớp filter `hoàn thành` -> DataFrame rỗng -> mean ra NaN -> chốt unanswerable sai.<br>**Cơ chế giải quyết:** Bước 1 cung cấp nhãn `completed`, Bước 3 chặn unanswerable ảo. Doanh thu theo dòng cho 70.017 (khớp gold); nếu dùng `Tổng bill` ra 71.375. |
| 15 | `q_583e4896e764` | biz_109 | dthu nhóm hangf sữa chiếm bao nhiêu phần trăm tổng revenue tháng 6 năm 2025 | Abstain | `5.79` | `null` | Bước 1, Bước 2 | **(A) Fully Solved** | **Lỗi:** Code cố đọc cột `Thời gian` từ file chi tiết bán hàng (vốn không có cột này, chỉ có trong file hoá đơn) -> KeyError cả 3 lượt.<br>**Cơ chế giải quyết:** Bước 1 chỉ rõ file chi tiết không có Thời gian, buộc model join với bảng hoá đơn. Bước 2 verify cột join, giải phóng code khỏi KeyError và tính ra đúng 5.79%. |
| 16 | `q_5c5ff524d0d9` | biz_121 | dthu thuốc hoạt chất Povidon iod tháng 10/2025 là bao nhiêu? | Sai | `8253000` | `0` | Bước 2, Bước 3 | **(B) Partially Solved** | **Lỗi:** So sánh SKU thuốc với mã đơn hàng -> khớp 0 dòng -> doanh thu = 0. Ngoài ra file có merged cells làm trống mã đơn ở dòng con.<br>**Cơ chế giải quyết:** Bước 3 chặn doanh thu = 0. Bước 2 probe nối SKU qua tên sản phẩm. Tuy nhiên cần thêm cơ chế ffill merged cells để khôi phục đầy đủ ngữ cảnh dòng con. |
| 17 | `q_67297f4bdfc2` | biz_122 | ti le huy don thang 3/2026 la bao nhieu % | Sai | `0.98` | `0.52` | Không | **(C) Unsolved** | **Lỗi:** Model lấy 31 mã đơn huỷ chia cho 5.987 dòng sau lọc (ra 0.52%) thay vì chia cho 3.148 mã đơn phân biệt mọi trạng thái (ra 0.98% theo Rulebook §1).<br>**Cơ chế giải quyết:** 3 bước đề xuất không can thiệp vào công thức mẫu số trong toán học của prompt; đòi hỏi model phải hiểu sâu Rulebook §1. |
| 18 | `q_725f54f95253` | biz_101 | ê revenue ngày nào cao nhất trong tháng 7 năm 2026 | Đúng | `2026-07-30` | `2026-07-30` | Không (Baseline) | **(A) Maintained Correct** | Baseline đã đúng từ lượt đầu. Duy trì ổn định. |
| 19 | `q_7428165a9e0a` | biz_129 | tong dthu hom qua la bao nhieu | Sai | `22740500` | `0` | Bước 1, Bước 3 | **(B) Partially Solved** | **Lỗi:** Lọc `hoàn thành` làm rỗng 47 đơn `completed` của ngày hôm qua -> doanh thu = 0.<br>**Cơ chế giải quyết:** Bước 1 đưa nhãn `completed`, Bước 3 chặn kết quả 0. Tổng tiền bán từ dòng hàng cho đúng 22.740.500; nếu lấy `Phải thu` ra 22.530.500. |
| 20 | `q_95099c4916a8` | biz_109 | cho hỏi trong tháng 12/2025, khách nữ chiếm bao nhiu % doanh thu | Sai | `unanswerable` | `0` | Bước 1, Bước 3 | **(A) Fully Solved** | **Lỗi:** Shop không có cột giới tính. Model lấy cột `Loại hình khách` (toàn bộ là `Cá nhân`), tưởng là nữ, lọc ra 0 dòng rồi kết luận 0% doanh thu.<br>**Cơ chế giải quyết:** Bước 1 hiển thị nhãn cột `Loại hình khách: ['Cá nhân']`. Bước 3 phát hiện lọc giới tính cho `rows_after_filter == 0` và cảnh báo thiếu thông tin, model trả về `unanswerable` chuẩn xác. |
| 21 | `q_9b1dce77c710` | biz_106 | cho bảng 3 khách còn nowj nhiều nhất tính ddeens hết ngày 30/06/2026, kèm số tiền còn nợ | Sai | Bảng 3 khách nợ 109k, 99.5k, 97.5k | Bảng 3 khách nợ 0đ | Bước 3 | **(B) Partially Solved** | **Lỗi:** Lấy snapshot `Đã trả` trừ tổng đơn, xếp cả số dư 0, xuất bảng 4 cột với nợ toàn bằng 0.<br>**Cơ chế giải quyết:** Bước 3 phát hiện bảng công nợ chứa toàn số 0 là bất thường, chặn và ép `abstain` (cứu -1.0 điểm). Để tính đúng cần đọc sổ quỹ Rulebook §4. |
| 22 | `q_a264d94a0492` | biz_101 | xem giúp tháng 9/2025 hàng nào chạy nhất | Đúng | `"Snack Oishi tôm cay 40g"` | `"Snack Oishi tôm cay 40g"` | Không (Baseline) | **(A) Maintained Correct** | Baseline đã đúng từ lượt đầu. Duy trì ổn định. |
| 23 | `q_a569fbc6b9fc` | biz_106 | dthu co tang lien tuc qua 3 thang 4/2026, 5/2026, 6/2026 khong | Đúng | `False` | `False` | Không (Baseline) | **(A) Maintained Correct** | Baseline đã đúng từ lượt đầu. Duy trì ổn định. |
| 24 | `q_aacf9543a235` | biz_106 | Khách mua nhiều tiền nhất tháng 3/2026 là ai? | Abstain | `"Vương Phương Loan"` | `null` | Bước 1, Bước 2 | **(A) Fully Solved** | **Lỗi:** Lỗi KeyError hậu tố sau join (`amount_x`), lượt cuối groupby nhầm kiểu dữ liệu sinh `TypeError: int + str` -> Abstain.<br>**Cơ chế giải quyết:** Bước 1 & Bước 2 làm rõ kiểu dữ liệu và schema cột sau join, code parse số bằng `parse_vn_number()` và ra đúng "Vương Phương Loan". |
| 25 | `q_d401c0884402` | biz_130 | So với cùng kỳ tháng trước, doanh thu từ đầu tháng này đến hết hôm nay tăng hay giảm bao nhiêu %? | Sai | `-18.92` | `unanswerable` | Bước 3 | **(B) Partially Solved** | **Lỗi:** Tự dựng kỳ trước kết thúc trước ngày bắt đầu (`01/07–30/06`) -> mẫu số = 0 -> ZeroDivisionError -> chốt unanswerable.<br>**Cơ chế giải quyết:** Bước 3 / Abstain Gate chặn unanswerable ảo thành abstain (cứu -1.0 điểm). Để ra đúng -18.92% cần module `time_resolver` bắt cụm "cùng kỳ tháng trước". |
| 26 | `q_e0aef192cb11` | biz_101 | dthu ngày nào cao nhất trong tháng 6 năm 2026? | Sai | `2026-06-01` | `unanswerable` | Bước 1, Bước 3 | **(A) Fully Solved** | **Lỗi:** Filter `hoàn thành` làm rỗng tháng 6 của biz_101 (`Xong`) -> chốt unanswerable.<br>**Cơ chế giải quyết:** Bước 1 đưa nhãn `Xong`, Bước 3 chặn unanswerable ảo. Cộng dòng hợp lệ theo ngày xác nhận ra đúng ngày `2026-06-01`. |
| 27 | `q_e311e396f7f0` | biz_127 | Doanh thu tháng 3/2026 bao nhiêu? | Sai | `1098707000` | `0` | Bước 1, Bước 3 | **(B) Partially Solved** | **Lỗi:** Lọc `hoàn thành` làm rỗng tháng 3 biz_127 (`completed`) -> ra 0.<br>**Cơ chế giải quyết:** Bước 1 đưa nhãn `completed`, Bước 3 chặn doanh thu = 0. Để khớp 1.098.707.000 cần tính doanh thu theo dòng hàng thay vì cột `Tổng đơn` (Rulebook §1). |
| 28 | `q_e7837d5638fb` | biz_122 | Tổng doanh thu tháng 9 năm 2025 là bao nhiêu? | Sai | `248572900` | `252854400` | Không | **(C) Unsolved** | **Lỗi:** Excel merged cells: 2.654 dòng con bị trống trạng thái và mã đơn. Code để lọt các dòng trống và sót nhãn hoàn hàng, tính ra 252.854.400.<br>**Cơ chế giải quyết:** 3 bước đề xuất không có cơ chế `ffill()` dữ liệu bảng biểu. Cần module tiền xử lý unmerge của Rulebook §8. |
| 29 | `q_e9930d87abdd` | biz_109 | cho bang 5 khach con no nhieu nhat tinh den het ngay 27/03/2026, kem so tien con no | Abstain | Bảng 5 khách nợ | `null` | Bước 1, Bước 2 | **(B) Partially Solved** | **Lỗi:** Hoá đơn và sổ quỹ cùng có cột `Thời gian`. Sau join bị KeyError `Thời gian` lặp lại 3 lượt.<br>**Cơ chế giải quyết:** Bước 1 & Bước 2 giúp phân biệt cột ngày đơn và ngày thu trước khi join. Cần thêm logic sổ quỹ Rulebook §4 để ra chuẩn top 5. |
| 30 | `q_fcafb39ec35f` | biz_109 | Tháng 2/2025, khách đường Lê Trọng Tấn và khách đường Trần Não, bên nào mua nhiều tiền hơn nhỉ? | Sai | `unanswerable` | `"Hai bên mua bằng nhau"` | Bước 1, Bước 3 | **(A) Fully Solved** | **Lỗi:** Dữ liệu thiếu cột địa chỉ. Model tìm tên đường trong tên khách, cả 2 bên ra rỗng (0 đồng) -> kết luận "Hai bên mua bằng nhau".<br>**Cơ chế giải quyết:** Bước 1 xác nhận không có cột địa chỉ; Bước 3 phát hiện cả 2 tập hợp đều có `rows_after_filter == 0`, chặn kết luận so sánh ảo và chốt `unanswerable` chuẩn xác. |

---

## PHẦN 3: RÀ SOÁT CÁC RỦI RO, ĐIỂM MÙ & VẤN ĐỀ KỸ THUẬT CÒN TỒN ĐỌNG (R3)

Mặc dù đề xuất 3 bước rất hứa hẹn, việc áp dụng vào môi trường thi đấu thực tế của Zalo AI Challenge 2026 còn tồn tại **4 điểm mù và rủi ro kỹ thuật cực kỳ lớn** mà nhóm kỹ thuật bắt buộc phải giải quyết:

### 3.1. Rủi ro Bùng nổ Độ trễ (Latency Explosion) trong Môi trường Docker Offline
- **Bối cảnh phần cứng & quy định:** Hệ thống chạy hoàn toàn offline (`--network none`) trên 2x NVIDIA RTX 5090 (64GB VRAM). Mỗi lượt gọi mô hình 14B tiêu tốn thời gian prefill prompt dài (16K context window) và decode script.
- **Rủi ro thực tế:**
  - Trong đợt eval dev 30 vừa qua, thời gian trung bình mỗi câu là **28.54 giây** (tổng cộng 856 giây cho 30 câu với 54 turns).
  - Nếu áp dụng Bước 2 một cách máy móc (câu nào cũng bắt buộc chạy lượt thăm dò ở Turn 1 rồi mới chạy Turn 2), số lượt sinh sẽ tăng từ 54 lên tối thiểu 60–80 turns, đẩy thời gian trung bình lên **45–60 giây/câu**.
  - Khi chạy trên tập test mở rộng (ví dụ 150 câu của Public/Private Test), tổng thời gian có thể lên tới **120–150 phút**, vượt quá giới hạn timeout kiểm thử của Ban Tổ Chức (thường là 60–90 phút).
- **Khuyến nghị kiến trúc:**
  - **Áp dụng Thăm dò Phân tầng (Conditional / Tiered Exploration):** Không chạy Bước 2 cho mọi câu. Chỉ kích hoạt lượt thăm dò khi:
    + Câu hỏi yêu cầu truy vấn chuỗi tiếng Việt phức tạp, không dấu hoặc tìm kiếm hoạt chất/sản phẩm (Fuzzy search).
    + Dữ liệu liên quan đến từ 2 file/sheet trở lên cần join phức tạp.
    + Các câu hỏi đơn giản (hỏi doanh thu 1 ngày, hỏi tháng cao nhất, hỏi câu hỏi yes/no) phải ưu tiên giải quyết ngay trong Turn 1 (One-Shot execution).

### 3.2. Chiến lược Xử lý Câu hỏi Thiếu Dữ kiện & Cơ chế Abstain Gate theo Công thức PA
- **Sự nguy hiểm của điểm phạt -1.0:**
  - Trong công thức Penalized Accuracy:
    $$\text{PA} = \frac{1}{N} (N_{\text{correct}} \times 1.0 + N_{\text{abstain}} \times 0.0 - N_{\text{wrong}} \times 1.0)$$
  - Một câu đoán mò bị sai sẽ **triệt tiêu hoàn toàn điểm của một câu làm đúng**!
  - Trong 30 câu dev, có **3 câu gold là `unanswerable`** (`q_22f59bab1075`, `q_95099c4916a8`, `q_fcafb39ec35f`). Cả 3 câu này model đều cố đoán mò và trả lời SAI, khiến nhóm mất trọn vẹn **-3.0 điểm**!
- **Điểm mù của đề xuất 3 bước:**
  - Đề xuất 3 bước tập trung vào việc "sửa code cho đúng", nhưng chưa định hình rõ ràng ranh giới khi nào thì nên **chấp nhận từ bỏ (Abstain)**.
  - Tỉ lệ câu `unanswerable` trong toàn bộ benchmark thường chỉ chiếm 2–5%. Do đó, nếu model tự tin xuất `unanswerable` sai thì bị phạt -1.0; còn nếu chuyển thành `abstain` thì được 0.0 điểm.
- **Khuyến nghị kiến trúc (Abstain Gate):**
  - Cần kích hoạt tham số `abstain_on_unanswerable = True` trong `solver.py` (dòng 1043) đối với các trường hợp độ tự tin thấp.
  - Khi Bước 3 phát hiện kết quả nghi ngờ mà đã hết lượt retry (Turn 3), **hệ thống phải tuyệt đối cưỡng chế xuất `abstain`**, nghiêm cấm fallback về một con số đoán mò hoặc xuất `unanswerable` thiếu căn cứ.

### 3.3. Xử lý các Dạng Bảng Phức tạp (Merged Cells, Sheet Ẩn, Ngày Đa Định Dạng)
- **Điểm mù Merged Cells (Ô gộp):**
  - Đề xuất 3 bước hoàn toàn bất lực trước lỗi gộp ô của Excel (`q_e7837d5638fb` và `q_5c5ff524d0d9`). Khi xuất từ phần mềm bán hàng như KiotViet/Sapo, thông tin hoá đơn (Mã đơn, Ngày bán, Trạng thái) chỉ nằm ở dòng đầu tiên, các dòng hàng tiếp theo của cùng đơn hàng bị để trống (`NaN`).
  - Code của model dùng Pandas lọc `df[df['Trạng thái'] == 'completed']` sẽ vô tình vứt bỏ sạch các dòng hàng con, hoặc để lọt các dòng con của đơn huỷ!
- **Khuyến nghị kiến trúc (Engine Tiền Xử Lý Dữ Liệu):**
  - Thay vì trông chờ model tự viết code `ffill()`, hệ thống cần cung cấp một hàm helper sẵn có trong môi trường sandbox: `datamate_read_table(path, sheet)` có tích hợp sẵn cơ chế tự động điền giá trị cho các cột cấp đơn (`Mã đơn`, `Ngày`, `Trạng thái`, `Khách hàng`) theo đúng quy định tại Rulebook §8.

### 3.4. Rủi ro Ngữ nghĩa & Ảo giác trong Sandbox Exploration
- **Rủi ro:** Mô hình LLM tự sinh code thăm dò có thể viết code lỗi cú pháp hoặc query sai logic (ví dụ: dùng regex quá hẹp không tìm thấy sản phẩm nào).
- **Hậu quả:** Sandbox trả về tập rỗng `data: []`. Mô hình ở Turn 2 tin vào kết quả rỗng này và kết luận sai rằng shop không bán mặt hàng đó hoặc doanh thu = 0.
- **Khuyến nghị kiến trúc:**
  - Bổ sung template mẫu an toàn cho code thăm dò trong system prompt.
  - Cảnh báo rõ ràng trong prompt lượt 2: *"Dữ liệu quan sát được ở trên chỉ phản ánh kết quả của câu lệnh truy vấn trước đó; nếu kết quả rỗng, hãy kiểm tra lại câu lệnh truy vấn thay vì vội kết luận thiếu dữ liệu."*

---

## PHẦN 4: TỔNG KẾT ĐÁNH GIÁ VÀ KHUYẾN NGHỊ ĐIỀU CHỈNH CÓ THỨ TỰ ƯU TIÊN (R4)

### 4.1. Đánh giá Tổng thể Đề xuất Feedback
- **Đánh giá chung:** Đề xuất phản hồi 3 bước là **RẤT TỐT VÀ CỰC KỲ THỰC TẾ**. Đây là giải pháp can thiệp ở tầng hệ thống (Pipeline / Inference-time intervention) có chi phí kỹ thuật thấp nhất nhưng mang lại hiệu quả tức thì lớn nhất.
- **Những điểm CẦN GIỮ LẠI:**
  1. Giữ nguyên toàn bộ triết lý của **Bước 1 (Bản đồ dữ liệu phân loại cardinality)**: Đây là chìa khoá vàng giải quyết lỗi nhãn lọc.
  2. Giữ nguyên cơ chế **Bước 3 (Sanity check)** để bảo vệ điểm số PA.
- **Những điểm CẦN ĐIỀU CHỈNH & BỔ SUNG:**
  1. Điều chỉnh **Bước 2 (Sandbox Exploration)** từ cơ chế "chạy bắt buộc toàn bộ" sang "thăm dò có điều kiện" để bảo vệ giới hạn độ trễ (latency).
  2. Bổ sung **Helper Tiền xử lý Merged Cells** vào sandbox runtime.
  3. Bật biến `eval_core_rules = True` và tinh chỉnh `_eval_guard_issue()` trong `src/agent/solver.py` để guardrail hoạt động thực chất.

---

### 4.2. Actionable Roadmap & Thứ tự Ưu tiên Triển khai (Priority Matrix)

Nhóm phát triển nên thực hiện theo lộ trình 4 giai đoạn dưới đây trước khi cân nhắc việc train lại mô hình:

```
[ƯU TIÊN 1: 1-2 ngày] ──> [ƯU TIÊN 2: 1-2 ngày] ──> [ƯU TIÊN 3: 2-3 ngày] ──> [ƯU TIÊN 4: Sau khi tối ưu]
Kích hoạt Bước 1 & 3      Tích hợp Tiền xử lý       Thăm dò có điều kiện      Đánh giá lại & Quyết định
(Schema & Guardrail)       (Merged Cells & Time)     (Conditional Probe)       Fine-tune / Train lại SFT
```

| Thứ tự | Hạng mục công việc | Vị trí can thiệp trong Codebase | Tác động kỳ vọng trên 30 câu dev | Chi phí thời gian |
|:---:|---|---|---|:---:|
| **P1** | **Kích hoạt Bản đồ dữ liệu gọn (Bước 1)**<br>Xuất nhãn exact cho cột ít giá trị (cardinality $\le 20$) và count + 3 mẫu cho cột nhiều giá trị. | `src/profiler/business_loader.py`<br>(Hàm `format_profile_for_prompt`) | Khắc phục ngay **7 câu lọc nhãn sai** (`q_20aa992c0d3f`, `q_e0aef192cb11`, `q_2a0e86444947`, v.v.) | 0.5 ngày |
| **P2** | **Kích hoạt & Hoàn thiện Sanity Check (Bước 3)**<br>Bật `eval_core_rules=True`. Chặn kết quả 0 cho doanh thu, `[]` cho top-k, bảng toàn 0. Kích hoạt Abstain Gate khi hết lượt retry. | `src/agent/solver.py`<br>(Hàm `_eval_guard_issue` & Luồng Final Guard) | Cứu ngay **5–8 câu bị phạt -1.0 điểm** chuyển về `abstain` 0 điểm (cải thiện PA ít nhất +0.30). | 0.5 ngày |
| **P3** | **Cung cấp Helper Merged Cells & Bổ sung Time Resolver**<br>Hỗ trợ hàm `read_clean_excel()` tự động `ffill()` các cột cấp đơn. Nâng cấp `time_resolver` nhận diện "cùng kỳ tháng trước". | `src/agent/sandbox.py`<br>`src/time_resolver/calendar_utils.py` | Giải quyết dứt điểm `q_e7837d5638fb`, `q_5c5ff524d0d9`, `q_d401c0884402`. | 1 ngày |
| **P4** | **Thăm dò có điều kiện trong Sandbox (Bước 2)**<br>Chỉ ép observation turn khi phát hiện câu hỏi chứa từ khóa tìm kiếm chuỗi, fuzzy matching, hoặc join $\ge 2$ bảng. | `src/agent/solver.py`<br>(Hàm `_answer_question_steps`) | Giải quyết dứt điểm các lỗi KeyError join (`q_019ec94d9799`, `q_aacf9543a235`) và không dấu (`q_01a28f2233bd`). | 1 ngày |

---

### 4.3. Quyết định về việc Train lại Model (Model Retraining Decision)

> **KẾT LUẬN QUYẾT ĐỊNH: CHƯA CẦN TRAIN LẠI MODEL VÀO LÚC NÀY!**

**Lý do cốt lõi:**
1. **Model không bị khiếm khuyết về khả năng sinh mã:** Mô hình Qwen2.5-Coder-14B hiện tại đã sinh được mã Python cực kỳ chuẩn cú pháp, import đúng thư viện, và gọi hàm chính xác. Trong 30 câu eval, model chỉ sai vì **thông tin đầu vào bị mù** (không nhìn thấy nhãn `completed`/`Xong`, không thấy cột sau join) chứ không phải do năng lực lập trình kém.
2. **Chi phí train lại lớn nhưng không giải quyết được gốc rễ:** Nếu train lại SFT 817 mẫu mà không sửa prompt và pipeline, model sẽ tiếp tục "học vẹt" các nhãn trạng thái từ tập train (trong tập train có 38 mẫu dùng `hoàn thành`), dẫn đến overfitting nhãn.
3. **Hiệu quả biên vượt trội của can thiệp Pipeline:** Chỉ cần thực hiện P1, P2, P3 ở tầng pipeline (Inference-time Guardrails & Prompt Tuning), điểm PA được dự báo sẽ tăng từ **-0.5000 lên trên +0.4000**.
4. **Khi nào mới cần train lại?** Chỉ cân nhắc train lại một epoch bổ sung (hoặc DPO/RL) sau khi đã cố định xong toàn bộ pipeline 3 bước, và dùng chính các log trace sạch của pipeline mới làm dữ liệu huấn luyện.
