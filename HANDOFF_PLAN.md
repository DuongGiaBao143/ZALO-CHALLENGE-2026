# KẾ HOẠCH BÀN GIAO KỸ THUẬT (HANDOFF PLAN)
## DỰ ÁN DATAMATE — ZALO AI CHALLENGE 2026
### KIẾN TRÚC TINH GỌN 6 LEAN HELPERS, SUY LUẬN REACT VỚI EPHEMERAL THINKING, CỔNG KIỂM DUYỆT ABSTAIN-FIRST VÀ HƯỚNG DẪN ĐÁNH GIÁ QWEN2.5-14B-INSTRUCT-1M

---

| Thông Tin Dự Án | Chi Tiết |
|---|---|
| **Dự án** | DataMate — Zalo AI Challenge 2026 |
| **Đề tài** | Natural-Language Vietnamese Question Answering over Tabular Data |
| **Mô hình mục tiêu** | `Qwen/Qwen2.5-14B-Instruct-1M` (14.7B tham số $\le 15\text{B}$, tuân thủ Rule 2) |
| **Tài liệu mục tiêu** | Kế hoạch Bàn giao Kỹ thuật cho Lập trình viên Triển khai |
| **Phiên bản tài liệu** | 1.0 — Final Comprehensive Technical Handoff |
| **Ngày ban hành** | 13/11/2026 |
| **Độ mật & Chế độ** | Tuyệt đối bảo toàn dữ liệu thô `data/` (Strictly Read-Only / Immutable) |

---

## MỤC LỤC CHI TIẾT

1. [TỔNG QUAN DỰ ÁN & MỤC TIÊU BÀN GIAO](#1-tổng-quan-dự-án--mục-tiêu-bàn-giao)
   - [1.1. Bối cảnh Cuộc thi Zalo AI Challenge 2026 — Đề tài DataMate](#11-bối-cảnh-cuộc-thi-zalo-ai-challenge-2026--đề-tài-datamate)
   - [1.2. Thể thức Penalized Accuracy (PA) & Nguyên Tắc Sống Còn](#12-thể-thức-penalized-accuracy-pa--nguyên-tắc-sống-còn)
   - [1.3. Mục tiêu Chiến lược của Kế hoạch Bàn giao](#13-mục-tiêu-chiến-lược-của-kế-hoạch-bàn-giao)
2. [ĐẶC TẢ BỘ 6 CÔNG CỤ TINH GỌN PHI NGÀNH NGHỀ (DOMAIN-AGNOSTIC LEAN HELPERS)](#2-đặc-tả-bộ-6-công-cụ-tinh-gọn-phi-ngành-nghề-domain-agnostic-lean-helpers)
   - [2.1. Phân Tích Khuyết Tật Của Thiết Kế Cũ & Lý Do Loại Bỏ](#21-phân-tích-khuyết-tật-của-thiết-kế-cũ--lý-do-loại-bỏ)
   - [2.2. Đặc Tả Chi Tiết 6 Công Cụ Tinh Gọn](#22-đặc-tả-chi-tiết-6-công-cụ-tinh-gọn)
     - [Helper 1: `explore_data`](#helper-1-explore_datafile-columnnone-keywordnone-n5)
     - [Helper 2: `fuzzy_find`](#helper-2-fuzzy_finddf_or_file-column-query-top_k5-cutoff05)
     - [Helper 3: `load_clean_df`](#helper-3-load_clean_dffile-sheet0-dedup_ordertrue-as_of_datenone-id_colnone)
     - [Helper 4: `resolve_date`](#helper-4-resolve_dateexpr-as_of_datenone)
     - [Helper 5: `emit_obs`](#helper-5-emit_obsdata-msg)
     - [Helper 6: `emit_final`](#helper-6-emit_finalanswer-type-evidence-checknone-reasonnone)
   - [2.3. Hướng Dẫn Tích Hợp Vào `src/agent/sandbox.py`](#23-hướng-dẫn-tích-hợp-vào-srcagentsandboxpy)
3. [GIAO THỨC SUY LUẬN REACT, EPHEMERAL THINKING & THÍCH ỨNG LUẬT ĐỘNG](#3-giao-thức-suy-luận-react-ephemeral-thinking--thích-ứng-luật-động)
   - [3.1. Giao Thức ReAct Tinh Gọn Đa Lượt](#31-giao-thức-react-tinh-gọn-đa-lượt)
   - [3.2. Cơ Chế Ephemeral Thinking: Tối Ưu Cửa Sổ Ngữ Cảnh 16.384 Tokens](#32-cơ-chế-ephemeral-thinking-tối-ưu-cửa-sổ-ngữ-cảnh-16384-tokens)
   - [3.3. Cơ Chế Thích Ứng Luật Động (Dynamic In-Context Rule Extraction)](#33-cơ-chế-thích-ứng-luật-động-dynamic-in-context-rule-extraction)
4. [CƠ CHẾ CỔNG ABSTAIN-FIRST GATE & XỬ LÝ LỖI THỰC NGHIỆM](#4-cơ-chế-cổng-abstain-first-gate--xử-lý-lỗi-thực-nghiệm)
   - [4.1. Pháp Y 4 Mẫu Lỗi Chí Mạng Trên Bộ 30 Dev Benchmark](#41-pháp-y-4-mẫu-lỗi-chí-mạng-trên-bộ-30-dev-benchmark)
   - [4.2. Bảng Phân Tích Chi Tiết Các Câu Hỏi Bị Sai Phạt Điểm Nặng](#42-bảng-phân-tích-chi-tiết-các-câu-hỏi-bị-sai-phạt-điểm-nặng)
   - [4.3. Kiến Trúc Cổng Kiểm Duyệt Đa Tầng (Multi-Layer Abstain Gate)](#43-kiến-trúc-cổng-kiểm-duyệt-đa-tầng-multi-layer-abstain-gate)
5. [HƯỚNG DẪN ĐÁNH GIÁ TRÊN GOOGLE COLAB & TINH CHỈNH LORA](#5-hướng-dẫn-đánh-giá-trên-google-colab--tinh-chỉnh-lora)
   - [5.1. Khẳng Định Nền Tảng Mô Hình `Qwen/Qwen2.5-14B-Instruct-1M`](#51-khẳng-định-nền-tảng-mô-hình-qwenqwen25-14b-instruct-1m)
   - [5.2. Quy Trình Đánh Giá Trên Colab (`Evaluate_Qwen25_14B_1M_Colab_G4.ipynb`)](#52-quy-trình-đánh-giá-trên-colab-evaluate_qwen25_14b_1m_colab_g4ipynb)
   - [5.3. Chuẩn Hóa Bộ Dữ Liệu Huấn Luyện SFT & Cấu Hình LoRA](#53-chuẩn-hóa-bộ-dữ-liệu-huấn-luyện-sft--cấu-hình-lora)
6. [KẾ HOẠCH BÀN GIAO & PHÂN BỔ CÔNG VIỆC TRIỂN KHAI (ROADMAP)](#6-kế-hoạch-bàn-giao--phân-bổ-công-việc-triển-khai-roadmap)
   - [6.1. Phân Rã Các Gói Nhiệm Vụ Kỹ Thuật (Work Breakdown Structure)](#61-phân-rã-các-gói-nhiệm-vụ-kỹ-thuật-work-breakdown-structure)
   - [6.2. Tiêu Chí Nghiệm Thu Kỹ Thuật Bắt Buộc (Acceptance Criteria)](#62-tiêu-chí-nghiệm-thu-kỹ-thuật-bắt-buộc-acceptance-criteria)

---

## 1. TỔNG QUAN DỰ ÁN & MỤC TIÊU BÀN GIAO

### 1.1. Bối cảnh Cuộc thi Zalo AI Challenge 2026 — Đề tài DataMate
Cuộc thi **Zalo AI Challenge 2026** đặt ra đề tài **DataMate — Natural-Language Vietnamese Question Answering over Tabular Data**. Hệ thống có nhiệm vụ đóng vai trò là một trợ lý thông minh phân tích dữ liệu kinh doanh, tiếp nhận các câu hỏi bằng ngôn ngữ tự nhiên tiếng Việt từ chủ doanh nghiệp, hộ kinh doanh cá thể, quán cà phê, nhà thuốc, tiệm sửa xe... và tự động truy vấn dữ liệu từ các tệp thô hỗn hợp (`.csv`, `.xlsx`, `.sqlite`) kèm tài liệu ngữ cảnh (`README.md`, `rulebook.md`) để đưa ra câu trả lời chính xác.

Dữ liệu thực tế tại Việt Nam có tính chất phi chuẩn hóa cực kỳ cao (*highly unstructured and messy tabular data*):
- Các file Excel bị gộp ô (*merged cells*) nhiều tầng, dòng tiêu đề bị đẩy xuống dòng 2, dòng 3.
- Định dạng ngày tháng không nhất quán (`DD/MM/YYYY`, `YYYY-MM-DD`, `thg M YYYY`, số serial Excel `45230`).
- Tên sản phẩm, khách hàng, phụ tùng bị viết tắt, viết thiếu dấu tiếng Việt, hoặc sai chính tả.
- Hệ thống trạng thái đơn hàng dùng nhãn tự do (`Xong`, `completed`, `hoàn thành`, `đã giao`, hoặc không có cột trạng thái mà ghi trong cột `Ghi chú`).

### 1.2. Thể thức Penalized Accuracy (PA) & Nguyên Tắc Sống Còn
Hiệu quả của giải pháp được đo lường duy nhất qua chỉ số **Penalized Accuracy (PA)** do Ban Tổ Chức quy định:

$$\text{PA} = \frac{1}{N} \sum_{i=1}^{N} S(y_i, \hat{y}_i)$$

Trong đó, điểm thành phần $S(y_i, \hat{y}_i)$ cho mỗi câu hỏi được định nghĩa:
* **$+1.0$ điểm**: Trả lời **CHÍNH XÁC** đáp án chuẩn (sau khi qua chuẩn hóa Unicode NFC và làm tròn).
* **$0.0$ điểm**: Trả về **`"abstain"`** (chủ động từ chối trả lời khi dữ liệu không đủ căn cứ hoặc độ tự tin thấp).
* **$-1.0$ điểm**: Trả lời **SAI** (hình phạt rất nặng nhằm triệt tiêu hoàn toàn hiện tượng ảo giác / hallucination).

```
                      HÀM ĐIỂM PENALIZED ACCURACY (PA)
       +1.0 pt ────────────────────────────────────────── TRẢ LỜI ĐÚNG
                                                         (Chính xác, có căn cứ)
        0.0 pt ────────────────────────────────────────── ABSTAIN
                                                         (Từ chối an toàn)
       -1.0 pt ────────────────────────────────────────── TRẢ LỜI SAI
                                                         (Đoán mò, lọc rỗng, ảo giác)
```

> [!CRITICAL]
> ### NGUYÊN TẮC SỐNG CÒN: "THÀ TỪ CHỐI CÒN HƠN ĐOÁN MÒ"
> Vì điểm sai bị trừ tới **$-1.0$ điểm** (thay vì $0.0$ như các bài toán QA thông thường), **một câu trả lời sai sẽ xóa sạch hoàn toàn điểm số của một câu trả lời đúng**. 
> - Nếu một mô hình trả lời đúng 15 câu nhưng đoán sai 15 câu $\to \text{PA} = (15 - 15) / 30 = \mathbf{0.0000}$.
> - Nếu mô hình trả lời đúng 15 câu và chủ động `abstain` 15 câu nghi ngờ $\to \text{PA} = (15 + 0) / 30 = \mathbf{+0.5000}$.
> Do đó, mọi quyết định thiết kế kiến trúc phải tuân thủ nguyên tắc: **Chủ động chuyển đổi mọi trường hợp nghi ngờ, rủi ro cao, hoặc thiếu căn cứ dữ liệu thành `"abstain"`**.

### 1.3. Mục tiêu Chiến lược của Kế hoạch Bàn giao
Tài liệu này bàn giao kiến trúc kỹ thuật tinh gọn, chuyển đổi toàn diện codebase hiện tại nhằm đạt được các mục tiêu đo lường được:
1. **Chuyển hóa Điểm số PA từ Âm sang Dương Cao**: Nâng điểm số từ mức âm hiện tại ($\text{PA} = -0.1667$ với Base Model và $-0.0667$ với Base + LoRA cũ) lên mức mục tiêu **$\text{PA} \ge +0.4000$** trên tập 30 câu Unseen Dev benchmark, và hướng tới **$\text{PA} \ge +0.5500$** trên Public Leaderboard.
2. **Triệt Tiêu Điểm Phạt $-1.0$**: Cắt giảm số câu sai từ 9–12 câu xuống còn $\le 2$ câu nhờ cơ chế Cổng Kiểm duyệt Đa tầng (**Abstain-First Gate**).
3. **Chuẩn Hóa Bộ 6 Lean Helpers Phi Ngành Nghề**: Xóa bỏ các monkey-patching ngầm và các logic gán cứng ngành nghề (`ma don`, `ma chung tu`), thay thế bằng 6 primitive xử lý bảng biểu/văn bản mạnh mẽ, tổng quát.
4. **Bảo Toàn Context Window 16.384 Tokens**: Triển khai cơ chế **Ephemeral Thinking** để giữ mức tăng trưởng token tuyến tính thấp (~950 tok/turn thay vì 2.850 tok/turn), ngăn chặn hoàn toàn lỗi tràn context tại Turn 5 và bảo toàn tính năng Prefix Caching của vLLM.
5. **Đảm Bảo Tuân Thủ Tuyệt Đối Ràng Buộc Phần Cứng & Thể Lệ**: Chạy offline 100% trong Docker, mô hình giữ nguyên `Qwen/Qwen2.5-14B-Instruct-1M` (14.7B params $\le 15\text{B}$ theo Rule 2), đáp ứng ngân sách thời gian trung bình $\le 15\text{s / câu}$ (tổng thời gian 500 câu private test $< 2.5\text{ giờ} \ll 6.0\text{ giờ}$ theo Rule 1).

---

## 2. ĐẶC TẢ BỘ 6 CÔNG CỤ TINH GỌN PHI NGÀNH NGHỀ (DOMAIN-AGNOSTIC LEAN HELPERS)

### 2.1. Phân Tích Khuyết Tật Của Thiết Kế Cũ & Lý Do Loại Bỏ

Khảo sát mã nguồn hiện tại trong `src/agent/sandbox.py` (dòng 89–135 và dòng 417–795) chỉ ra 3 khiếm khuyết kiến trúc nghiêm trọng:

1. **Lạm Dụng Monkey-Patching Ngầm (Implicit Monkey-Patching)**:
   Mã nguồn cũ monkey-patch hơn 12 hàm của thư viện Python chuẩn và bên thứ ba: `json.dumps`, `pd.to_datetime`, `pd.read_csv`, `pd.read_excel`, `sqlite3.connect`, `pd.Series.__lt__/__le__/__gt__/__ge__/__eq__`, `pd.Series.sum`, `pd.Series.mean`, `pd.Series.dt`. Thiết kế này tạo ra các hành vi "ma thuật ngầm" khiến việc debug cực kỳ khó khăn khi xảy ra xung đột kiểu dữ liệu, đồng thời không cung cấp cho LLM các hàm có chữ ký (signature) tường minh, khiến LLM vẫn sinh code thủ công lặp đi lặp lại.
2. **Gán Cứng Logic Ngành Nghề (Hardcoded Domain Logic)**:
   Trong hàm `unmerge_and_ffill`:
   ```python
   # ĐOẠN CODE CŨ GÂY LỖI GÃY NGÀNH MỚI:
   for c, norm_c in norm_col_map.items():
       if any(k in norm_c for k in ['ma don', 'ma chung tu', 'ma phieu', 'ma hoa don', 'so chung tu', 'so hoa don', 'order id', 'invoice id']):
           detected_id = c
           break
   ```
   Logic này chỉ phù hợp với bán lẻ truyền thống ở tập Train. Khi bước sang Public Test (ngành Mẹ và bé, Sửa xe dùng `Biển số xe`, `Số phiếu sửa chữa`) và Private Test (Salon tóc dùng `Mã đặt lịch`, Vận tải dùng `Mã vận đơn`, Bệnh viện dùng `Mã toa thuốc`), bộ phát hiện này tê liệt hoàn toàn, dẫn đến việc unmerge thất bại và làm mất tới 40% số dòng dữ liệu.
3. **Thiếu Primitives Khám Phá & Tìm Kiếm Mờ**:
   Thiết kế cũ thiếu công cụ để LLM thăm dò nhãn thực tế của cột trước khi viết code lọc. LLM buộc phải đoán nhãn (ví dụ đoán `.str.contains("hoàn thành")` trong khi shop ghi `Xong`), dẫn đến DataFrame bị rỗng và nộp kết quả sai.

### 2.2. Đặc Tả Chi Tiết 6 Công Cụ Tinh Gọn

Bộ 6 Lean Helpers được thiết kế thuần túy dựa trên các generic tabular/text primitives, hoàn toàn độc lập với mọi ngành nghề kinh doanh:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   BỘ 6 DOMAIN-AGNOSTIC LEAN HELPERS (src/agent/sandbox.py)       │
├─────────────────────────┬────────────────────────────────────────────────────────┤
│ Helper                  │ Mục đích kỹ thuật cốt lõi                              │
├─────────────────────────┼────────────────────────────────────────────────────────┤
│ 1. explore_data()       │ Khám phá schema, dtypes, nulls, date coverage & sample │
│ 2. fuzzy_find()         │ Tìm kiếm mờ tiếng Việt xóa dấu, gợi ý top-k thực thể   │
│ 3. load_clean_df()      │ Đọc bảng tự unmerge, dò header, khử trùng lặp & lọc ngày│
│ 4. resolve_date()       │ Phân giải mốc thời gian tương đối & lịch âm/Tết        │
│ 5. emit_obs()           │ Xuất protocol observation chuẩn, tự khử NaN, bound 4k  │
│ 6. emit_final()         │ Xuất protocol final có sanity checks & guard an toàn   │
└─────────────────────────┴────────────────────────────────────────────────────────┘
```

---

#### Helper 1: `explore_data(file, column=None, keyword=None, n=5)`

##### 1. Mục Đích Kỹ Thuật
Cung cấp cái nhìn toàn cảnh tức thì về một tập tin dữ liệu (`.csv`, `.xlsx`, `.sqlite`) mà không cần nạp toàn bộ dữ liệu vào ngữ cảnh LLM:
- Kiểm tra danh sách bảng/sheet, số dòng, số cột, kiểu dữ liệu, số lượng ô trống.
- Khám phá độ bao phủ thời gian `[min_date, max_date]` trên các cột thời gian.
- Liệt kê các giá trị phân loại độc nhất (`unique_values`) của một cột cụ thể.
- Quét nhanh xem từ khóa `keyword` xuất hiện ở những cột nào và dòng nào.

##### 2. Signature & Kiểu Dữ Liệu Tham Số
```python
def explore_data(
    file: Union[str, Path],
    column: Optional[str] = None,
    keyword: Optional[str] = None,
    n: int = 5
) -> Dict[str, Any]:
```
- `file` (`str | Path`): Tên hoặc đường dẫn file cần khám phá (tự động phân giải trong `BUSINESS_DIR`).
- `column` (`str | None`, mặc định `None`): Tên cột cần phân tích sâu (dtype, unique_count, unique_values, null_count).
- `keyword` (`str | None`, mặc định `None`): Từ khóa tìm kiếm nhanh trên tất cả các cột văn bản (không phân biệt hoa thường và dấu tiếng Việt).
- `n` (`int`, mặc định `5`): Số dòng mẫu hoặc số giá trị độc nhất tối đa trả về.

##### 3. Dữ Liệu Trả Về (Return Schema)
- Khi chỉ truyền `file`:
  ```json
  {
    "file": "SoBanHang.xlsx",
    "sheets": ["T01_2026", "T02_2026"],
    "active_sheet": "T01_2026",
    "shape": [4250, 10],
    "columns": ["Mã đơn", "Ngày lập", "Trạng thái", "Tổng tiền"],
    "dtypes": {"Mã đơn": "object", "Ngày lập": "datetime64[ns]", "Tổng tiền": "float64"},
    "null_counts": {"Trạng thái": 12},
    "date_coverage": {"Ngày lập": ["2026-01-01", "2026-01-31"]},
    "head_sample": [{"Mã đơn": "DH001", "Trạng thái": "Xong", "Tổng tiền": 120000}]
  }
  ```
- Khi truyền `column="Trạng thái"`:
  ```json
  {
    "file": "SoBanHang.xlsx",
    "column": "Trạng thái",
    "dtype": "object",
    "total_rows": 4250,
    "null_count": 0,
    "unique_count": 3,
    "unique_values": ["Xong", "Đang giao", "Hủy"]
  }
  ```

##### 4. Xử Lý Tình Huống Biên (Edge Cases)
- File không tồn tại $\to$ Trả về dict báo lỗi rõ ràng kèm danh sách toàn bộ các file thực tế có trong thư mục shop (`available_files`).
- File SQLite $\to$ Trích xuất danh sách bảng từ `sqlite_master` và lược đồ cột qua `PRAGMA table_info`.
- Cột ngày tháng định dạng lẫn lộn $\to$ Tự động dùng `parse_vn_date` để trích xuất `min_date` và `max_date`.

##### 5. Mã Nguồn Tham Khảo / Pseudo-code Chi Tiết
```python
def explore_data(file, column=None, keyword=None, n=5):
    resolved = _smart_resolve_file(file)
    if not os.path.exists(resolved):
        available = os.listdir(BUSINESS_DIR) if os.path.exists(BUSINESS_DIR) else []
        return {"error": f"FileNotFound: {file}", "available_files": available}
    
    ext = os.path.splitext(resolved)[1].lower()
    if ext == ".sqlite":
        con = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
        cur = con.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if not column and not keyword:
            schema_info = {}
            for t in tables[:10]:
                cols = [c[1] for c in cur.execute(f'PRAGMA table_info("{t}")').fetchall()]
                cnt = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                schema_info[t] = {"columns": cols, "row_count": cnt}
            con.close()
            return {"file": os.path.basename(resolved), "type": "sqlite", "tables": schema_info}
        df = pd.read_sql_query(f'SELECT * FROM "{tables[0]}" LIMIT 2000', con)
        con.close()
        sheet_names = tables
    elif ext in (".xlsx", ".xls"):
        xls = pd.ExcelFile(resolved)
        sheet_names = xls.sheet_names
        df = load_clean_df(resolved, sheet=sheet_names[0])
    else:
        sheet_names = []
        df = load_clean_df(resolved)

    if column:
        if column not in df.columns:
            matches = difflib.get_close_matches(column, [str(c) for c in df.columns], n=3)
            return {"error": f"ColumnNotFound: {column}", "suggestions": matches}
        s = df[column]
        uniq = s.dropna().unique().tolist()
        return {
            "column": column,
            "dtype": str(s.dtype),
            "total_rows": len(df),
            "null_count": int(s.isna().sum()),
            "unique_count": len(uniq),
            "unique_values": uniq[:30]
        }
    
    if keyword:
        kw_norm = vn_norm(keyword).lower()
        match_cols = []
        matching_rows = []
        for c in df.columns:
            if df[c].dtype == object or pd.api.types.is_string_dtype(df[c]):
                mask = df[c].astype(str).apply(lambda x: kw_norm in vn_norm(x).lower())
                if mask.any():
                    match_cols.append(c)
                    if len(matching_rows) < n:
                        matching_rows.extend(df[mask].head(n - len(matching_rows)).to_dict(orient="records"))
        return {
            "keyword": keyword,
            "matching_columns": match_cols,
            "match_count": len(matching_rows),
            "samples": matching_rows
        }

    date_cov = {}
    for c in df.columns:
        if any(w in c.lower() for w in ("ngay", "date", "time")) or pd.api.types.is_datetime64_any_dtype(df[c]):
            dt_s = parse_vn_date(df[c]).dropna()
            if not dt_s.empty:
                date_cov[c] = [dt_s.min().strftime("%Y-%m-%d"), dt_s.max().strftime("%Y-%m-%d")]

    return {
        "file": os.path.basename(resolved),
        "sheets": sheet_names,
        "shape": list(df.shape),
        "columns": list(df.columns),
        "dtypes": {str(c): str(df[c].dtype) for c in df.columns},
        "null_counts": {str(c): int(df[c].isna().sum()) for c in df.columns if df[c].isna().any()},
        "date_coverage": date_cov,
        "head_sample": _sanitize_obs_nan(df.head(n).to_dict(orient="records"))
    }
```

---

#### Helper 2: `fuzzy_find(df_or_file, column, query, top_k=5, cutoff=0.5)`

##### 1. Mục Đích Kỹ Thuật
Tìm kiếm mờ thực thể tiếng Việt xóa dấu cho tên sản phẩm, khách hàng, nhân viên, hoặc linh kiện bị viết tắt, thiếu dấu hoặc sai chính tả trong câu hỏi:
- Chuẩn hóa Unicode NFC và xóa dấu qua `vn_norm()`.
- Kết hợp kiểm tra chứa chuỗi con (`substring containment`) và độ tương đồng `difflib.SequenceMatcher`.
- Trả về danh sách ứng viên có độ khớp cao nhất kèm số lần xuất hiện trong bảng dữ liệu.

##### 2. Signature & Kiểu Dữ Liệu Tham Số
```python
def fuzzy_find(
    df_or_file: Union[pd.DataFrame, str, Path],
    column: str,
    query: str,
    top_k: int = 5,
    cutoff: float = 0.5
) -> List[Dict[str, Any]]:
```
- `df_or_file`: Đối tượng DataFrame hoặc đường dẫn file cần tìm kiếm.
- `column`: Tên cột chứa văn bản cần so khớp.
- `query`: Chuỗi tìm kiếm do người dùng đặt trong câu hỏi.
- `top_k` (`int`, mặc định `5`): Số lượng kết quả khớp cao nhất trả về.
- `cutoff` (`float`, mặc định `0.5`): Ngưỡng tương đồng tối thiểu (0.0 đến 1.0).

##### 3. Dữ Liệu Trả Về
```json
[
  {
    "matched_value": "Soda chanh dây (M)",
    "score": 0.95,
    "count": 48
  },
  {
    "matched_value": "Soda chanh dây (L)",
    "score": 0.92,
    "count": 32
  }
]
```

##### 4. Xử Lý Tình Huống Biên
- Cột không tồn tại $\to$ Tự động gợi ý các cột gần đúng nhất bằng `difflib.get_close_matches`.
- Cột chứa toàn giá trị `NaN` hoặc toàn số $\to$ Chuyển đổi an toàn qua `dropna().astype(str)`.
- Không tìm thấy mục nào $\ge \text{cutoff}$ $\to$ Trả về mảng rỗng `[]`, không throw Exception.

##### 5. Mã Nguồn Tham Khảo / Pseudo-code Chi Tiết
```python
def fuzzy_find(df_or_file, column, query, top_k=5, cutoff=0.5):
    if isinstance(df_or_file, (str, Path)):
        df = load_clean_df(df_or_file)
    elif isinstance(df_or_file, pd.DataFrame):
        df = df_or_file
    else:
        raise ValueError(f"df_or_file must be DataFrame or path, got {type(df_or_file).__name__}")

    if column not in df.columns:
        col_matches = difflib.get_close_matches(column, [str(c) for c in df.columns], n=3)
        return [{"error": f"ColumnNotFound: {column}", "suggested_columns": col_matches}]

    s = df[column].dropna().astype(str)
    val_counts = s.value_counts()
    unique_vals = list(val_counts.index)

    q_norm = vn_norm(query).lower().strip()
    results = []

    for val in unique_vals:
        v_norm = vn_norm(val).lower().strip()
        if q_norm == v_norm:
            score = 1.0
        elif q_norm in v_norm:
            score = 0.90 + 0.10 * (len(q_norm) / max(1, len(v_norm)))
        else:
            score = difflib.SequenceMatcher(None, q_norm, v_norm).ratio()
        
        if score >= cutoff:
            results.append({
                "matched_value": val,
                "score": round(score, 3),
                "count": int(val_counts[val])
            })

    results.sort(key=lambda x: (x["score"], x["count"]), reverse=True)
    return results[:top_k]
```

---

#### Helper 3: `load_clean_df(file, sheet=0, dedup_order=True, as_of_date=None, id_col=None)`

##### 1. Mục Đích Kỹ Thuật
Tự động hóa toàn bộ quy trình tiền xử lý bảng biểu phức tạp theo quy chuẩn Rulebook §8:
- **Tự dò hàng Header**: Tự động bỏ qua các dòng tiêu đề rác, banner phía trên để nhận diện đúng hàng tiêu đề thực.
- **Unmerge & Forward-fill Đa Tầng**: Kế thừa thông tin từ dòng đầu đơn hàng (Mã đơn, Ngày lập, Trạng thái, Tên khách) xuống các dòng con chi tiết sản phẩm.
- **Ngăn Chặn Rò Rỉ Đơn Hàng (Cross-Order Leakage Prevention)**: Đảm bảo dòng của "Khách lẻ" ở đơn sau không bị ghi đè nhầm tên của khách hàng ở đơn trước.
- **Khử Trùng Lặp Nội Bộ Đơn Hàng (Rulebook §8)**: Tự động loại bỏ các dòng sản phẩm trùng lặp 100% trong cùng một đơn (do lỗi xuất file của phần mềm POS).
- **Lọc Chặn Tương Lai (`as_of_date` Guard)**: Loại bỏ các bản ghi có ngày phát sinh $> \text{as\_of\_date}$, ngăn chặn rò rỉ dữ liệu tương lai.

##### 2. Signature & Kiểu Dữ Liệu Tham Số
```python
def load_clean_df(
    file: Union[str, Path],
    sheet: Union[int, str] = 0,
    dedup_order: bool = True,
    as_of_date: Optional[str] = None,
    id_col: Optional[str] = None
) -> pd.DataFrame:
```
- `file`: Đường dẫn file `.csv`, `.xlsx`, hoặc `.sqlite`.
- `sheet`: Tên sheet hoặc index sheet (mặc định 0).
- `dedup_order` (`bool`, mặc định `True`): Tự động khử trùng lặp dòng chi tiết trong cùng mã đơn theo Rulebook §8.
- `as_of_date` (`str | None`): Ngày mốc `YYYY-MM-DD`. Nếu có, tự động lọc `df[date_col] <= as_of_date`.
- `id_col` (`str | None`): Tên cột định danh đơn hàng/phiếu nếu muốn chỉ định tường minh.

##### 3. Dữ Liệu Trả Về
Đối tượng `pd.DataFrame` đã được unmerge, khử trùng, ép kiểu ngày/tiền tệ chuẩn, sẵn sàng 100% cho các phép tính tổng hợp (`groupby`, `sum`, `count`) mà không bị mất dòng hay lệch số liệu.

##### 4. Xử Lý Tình Huống Biên
- File Excel có merged cells nhưng không có cột mã đơn rõ ràng $\to$ Tự động dò cột có độ rỗng xen kẽ theo chu kỳ để xác định khối nhóm.
- Định dạng ngày tháng kiểu phân số hoặc serial number $\to$ Tự động chuyển đổi thành `datetime64[ns]`.

##### 5. Mã Nguồn Tham Khảo / Pseudo-code Chi Tiết
```python
def load_clean_df(file, sheet=0, dedup_order=True, as_of_date=None, id_col=None):
    resolved = _smart_resolve_file(file)
    ext = os.path.splitext(resolved)[1].lower()

    if ext in (".xlsx", ".xls"):
        df = _orig_read_excel(resolved, sheet_name=sheet)
        if isinstance(df, dict):
            df = next(iter(df.values()))
        df = _detect_best_header(df)
        df = unmerge_and_ffill(df, id_col=id_col)
    elif ext == ".csv":
        df = _orig_read_csv(resolved)
        df = _detect_best_header(df)
        df = unmerge_and_ffill(df, id_col=id_col)
    elif ext == ".sqlite":
        con = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
        tbl_name = str(sheet) if isinstance(sheet, str) and sheet != "0" else None
        if not tbl_name:
            cur = con.cursor()
            tbl_name = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone()[0]
        df = pd.read_sql_query(f'SELECT * FROM "{tbl_name}"', con)
        con.close()
    else:
        raise ValueError(f"Unsupported file format: {ext}")

    # Khử trùng lặp nội bộ dòng chi tiết trong đơn hàng (Rulebook §8)
    if dedup_order and len(df) > 0:
        order_key = id_col
        if not order_key:
            norm_cols = {c: vn_norm(c).lower().replace('_', ' ').strip() for c in df.columns}
            for c, nc in norm_cols.items():
                if any(k in nc for k in ('ma don', 'ma chung tu', 'so hoa don', 'so phieu', 'order id', 'invoice id')):
                    order_key = c
                    break
        if order_key and order_key in df.columns:
            df = df.drop_duplicates()

    # Lọc chặn theo as_of_date (Rulebook §2)
    cutoff_date = as_of_date or globals().get("AS_OF_DATE", None)
    if cutoff_date and len(df) > 0:
        date_col = None
        norm_cols = {c: vn_norm(c).lower().replace('_', ' ').strip() for c in df.columns}
        for c, nc in norm_cols.items():
            if any(k in nc for k in ('ngay lap', 'ngay dat', 'ngay ban', 'ngay chung tu', 'ngay sua', 'date', 'order date')):
                date_col = c
                break
        if not date_col:
            for c in df.columns:
                if 'ngay' in c.lower():
                    date_col = c
                    break
        if date_col:
            dt_series = parse_vn_date(df[date_col])
            target_dt = pd.to_datetime(cutoff_date)
            # Giữ các dòng NaN ngày (nếu có) hoặc <= cutoff_date hết ngày
            valid_mask = dt_series.isna() | (dt_series <= target_dt + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1))
            df = df[valid_mask].copy()

    return df
```

---

#### Helper 4: `resolve_date(expr, as_of_date=None)`

##### 1. Mục Đích Kỹ Thuật
Phân giải chuẩn hóa các biểu thức thời gian tiếng Việt theo quy định Rulebook §2 và tra cứu lịch âm/dương động từ `calendar.csv`:
- Phân giải các mốc tương đối: *"hôm nay"*, *"hôm qua"*, *"tuần này"* (từ Thứ 2 đến `as_of_date`), *"tuần trước"* (trọn vẹn 7 ngày tuần trước), *"tháng này"* (từ ngày 01 đến `as_of_date`), *"tháng trước"* (trọn vẹn cả tháng trước), *"cùng kỳ tháng trước"* (từ ngày 01 đến ngày trùng số với `as_of_date` ở tháng trước).
- Tra cứu Dịp Tết năm Y: Bắt đầu từ **23 tháng Chạp năm âm $Y-1$** đến hết **mùng 10 tháng Giêng năm âm $Y$** từ `calendar.csv`.
- Phân giải ca làm việc: Ca sáng (`06:00 – 13:59`), Ca chiều (`14:00 – 21:59`).
- Xử lý ngày thứ X trong kỳ: Đếm đúng tổng số ngày thứ X theo lịch trong kỳ (Rulebook §2 bổ sung).

##### 2. Signature & Kiểu Dữ Liệu Tham Số
```python
def resolve_date(
    expr: str,
    as_of_date: Optional[str] = None
) -> Dict[str, Any]:
```
- `expr`: Biểu thức thời gian tiếng Việt (ví dụ `"tháng này"`, `"cùng kỳ tháng trước"`, `"tuần rồi"`, `"dịp tết 2026"`).
- `as_of_date`: Ngày mốc `YYYY-MM-DD`. Nếu không truyền, tự động đọc biến môi trường `AS_OF_DATE`.

##### 3. Dữ Liệu Trả Về
```json
{
  "expr": "cùng kỳ tháng trước",
  "as_of_date": "2026-03-31",
  "start_date": "2026-02-01",
  "end_date": "2026-02-28",
  "prev_start_date": null,
  "prev_end_date": null,
  "description": "Cùng kỳ tháng trước của 2026-03-31 kẹp về ngày cuối tháng 2 (2026-02-28)"
}
```

##### 4. Xử Lý Tình Huống Biên
- Kẹp ngày cuối tháng (Month-end clamping): `as_of_date` là ngày 31/03, tháng 2 có 28 ngày $\to$ kẹp về 28/02.
- Năm nhuận: Tháng 2 năm 2024 có 29 ngày $\to$ kẹp về 29/02.
- Không tìm thấy `calendar.csv` $\to$ Sử dụng bảng tra cứu ngoại tuyến tích hợp sẵn cho Tết 2025 (`2025-01-22 .. 2025-02-07`) và Tết 2026 (`2026-02-10 .. 2026-02-26`).

##### 5. Mã Nguồn Tham Khảo / Pseudo-code Chi Tiết
```python
def resolve_date(expr, as_of_date=None):
    base_date_str = as_of_date or globals().get("AS_OF_DATE", "")
    if not base_date_str:
        raise ValueError("as_of_date must be provided or AS_OF_DATE set in sandbox environment.")
    
    base_dt = pd.to_datetime(base_date_str)
    q_norm = vn_norm(expr).lower().strip()
    
    # 1. Các mốc ngày đơn
    if any(k in q_norm for k in ("hom nay", "today")):
        d_str = base_dt.strftime("%Y-%m-%d")
        return {"start_date": d_str, "end_date": d_str, "description": "Hôm nay"}
    if any(k in q_norm for k in ("hom qua", "yesterday")):
        d_str = (base_dt - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        return {"start_date": d_str, "end_date": d_str, "description": "Hôm qua"}

    # 2. Tuần này: Thứ 2 đến hết as_of_date
    if "tuan nay" in q_norm:
        monday = base_dt - pd.Timedelta(days=base_dt.weekday())
        return {
            "start_date": monday.strftime("%Y-%m-%d"),
            "end_date": base_dt.strftime("%Y-%m-%d"),
            "description": "Tuần này (Thứ 2 đến hết as_of_date)"
        }
    
    # 3. Tuần trước: Trọn vẹn 7 ngày tuần trước
    if any(k in q_norm for k in ("tuan truoc", "tuan roi")):
        monday_this_week = base_dt - pd.Timedelta(days=base_dt.weekday())
        monday_last_week = monday_this_week - pd.Timedelta(days=7)
        sunday_last_week = monday_this_week - pd.Timedelta(days=1)
        return {
            "start_date": monday_last_week.strftime("%Y-%m-%d"),
            "end_date": sunday_last_week.strftime("%Y-%m-%d"),
            "description": "Tuần trước (Thứ 2 đến Chủ nhật trọn vẹn)"
        }

    # 4. Cùng kỳ tháng trước (Rulebook §2)
    if "cung ky" in q_norm or "so voi thang truoc" in q_norm:
        y, m, d = base_dt.year, base_dt.month, base_dt.day
        prev_m = 12 if m == 1 else m - 1
        prev_y = y - 1 if m == 1 else y
        max_d_prev = calendar.monthrange(prev_y, prev_m)[1]
        clamped_d = min(d, max_d_prev)
        return {
            "start_date": f"{prev_y:04d}-{prev_m:02d}-01",
            "end_date": f"{prev_y:04d}-{prev_m:02d}-{clamped_d:02d}",
            "description": f"Cùng kỳ tháng trước (01 đến {clamped_d:02d}/{prev_m:02d})"
        }

    # 5. Tháng này: 01 đến hết as_of_date
    if "thang nay" in q_norm:
        return {
            "start_date": f"{base_dt.year:04d}-{base_dt.month:02d}-01",
            "end_date": base_dt.strftime("%Y-%m-%d"),
            "description": "Tháng này (01 đến hết as_of_date)"
        }

    # 6. Tháng trước trọn vẹn
    if any(k in q_norm for k in ("thang truoc", "thang roi")):
        y, m = base_dt.year, base_dt.month
        prev_m = 12 if m == 1 else m - 1
        prev_y = y - 1 if m == 1 else y
        last_d = calendar.monthrange(prev_y, prev_m)[1]
        return {
            "start_date": f"{prev_y:04d}-{prev_m:02d}-01",
            "end_date": f"{prev_y:04d}-{prev_m:02d}-{last_d:02d}",
            "description": f"Tháng trước trọn vẹn ({prev_m:02d}/{prev_y:04d})"
        }

    # 7. Dịp Tết từ calendar.csv
    if "tet" in q_norm:
        cal_path = globals().get("CALENDAR_PATH", "")
        if cal_path and os.path.exists(cal_path):
            cdf = pd.read_csv(cal_path)
            # Tìm năm Tết
            target_year = base_dt.year
            m_year = re.search(r'202\d', q_norm)
            if m_year:
                target_year = int(m_year.group(0))
            
            # Bắt đầu: 23 tháng Chạp năm target_year - 1
            s_rows = cdf[(cdf["lunar_year"] == target_year - 1) & (cdf["lunar_month"] == 12) & (cdf["lunar_day"] == 23)]
            # Kết thúc: mùng 10 tháng Giêng năm target_year
            e_rows = cdf[(cdf["lunar_year"] == target_year) & (cdf["lunar_month"] == 1) & (cdf["lunar_day"] == 10)]
            if not s_rows.empty and not e_rows.empty:
                s_date = str(s_rows.iloc[0]["date"])
                e_date = str(e_rows.iloc[0]["date"])
                return {
                    "start_date": s_date,
                    "end_date": e_date,
                    "description": f"Dịp Tết {target_year} (23 Chạp đến mùng 10 Tết)"
                }

    # Fallback mặc định: ngày as_of_date
    d_str = base_dt.strftime("%Y-%m-%d")
    return {"start_date": d_str, "end_date": d_str, "description": "Mặc định as_of_date"}
```

---

#### Helper 5: `emit_obs(data, msg="")`

##### 1. Mục Đích Kỹ Thuật
Chuẩn hóa dữ liệu quan sát trung gian giữa các turn ReAct gửi về cho mô hình ngôn ngữ:
- Tự động chuyển đổi các kiểu dữ liệu phức tạp của Pandas/NumPy (`DataFrame`, `Series`, `ndarray`, `Timestamp`, `int64`, `float64`) thành cấu trúc JSON hợp lệ.
- Thay thế toàn bộ `NaN`, `NaT`, `Infinity`, `-Infinity` thành `null` để không vi phạm hàm `_parse_strict_json`.
- Cắt ngắn an toàn trong giới hạn **4.000 ký tự** (`MAX_OBSERVATION_DATA_CHARS`) để ngăn chặn việc in toàn bộ bảng làm tràn context window 16.384 tokens.
- In JSON hợp lệ trên dòng stdout cuối cùng.

##### 2. Signature & Kiểu Dữ Liệu Tham Số
```python
def emit_obs(
    data: Any,
    msg: str = ""
) -> None:
```
- `data`: Bất kỳ đối tượng dữ liệu nào cần quan sát (DataFrame tự động lấy `.head(10).to_dict()`).
- `msg`: Thông điệp tóm tắt ngắn gọn (tối đa 500 ký tự).

##### 3. Dữ Liệu Trả Về (In ra Stdout)
```json
{"kind": "observation", "data": [{"Trạng thái": "Xong", "Số đơn": 412}], "message": "Đã khám phá cột trạng thái"}
```

##### 4. Mã Nguồn Tham Khảo / Pseudo-code Chi Tiết
```python
def emit_obs(data, msg=""):
    clean_data = _sanitize_obs_nan(_default_json_enc(data))
    payload = {
        "kind": "observation",
        "data": clean_data,
        "message": str(msg)[:500] if msg else ""
    }
    dumped = json.dumps(payload, ensure_ascii=False, default=_default_json_enc)
    if len(dumped) > 4000:
        payload["data_truncated"] = True
        payload["data"] = str(clean_data)[:3400] + "... [truncated]"
        dumped = json.dumps(payload, ensure_ascii=False)
    print(dumped)
```

---

#### Helper 6: `emit_final(answer, type, evidence, check=None, reason=None)`

##### 1. Mục Đích Kỹ Thuật
Xuất kết quả chốt cuối cùng tuân thủ 100% giao thức JSON của Ban Tổ Chức:
- Định dạng kiểu dữ liệu tự động: Làm tròn số tối đa 2 chữ số thập phân (`round(val, 2)`), định dạng phần trăm (`round(val * 100, 2)` nếu cần), định dạng ngày ISO `YYYY-MM-DD`, chuẩn hóa Unicode NFC cho chuỗi và danh sách.
- **Tích Hợp Sanity Check Chống Bẫy Lọc Rỗng**:
  * Nếu kết quả số đo $= 0$ mà truyền `check={"rows_after_filter": 0}` $\to$ Tự động chuyển đổi thành `"abstain"` (nhận 0.0 điểm thay vì bị phạt $-1.0$ điểm do bẫy lọc rỗng!).
  * Nếu `type="unanswerable"`, bắt buộc phải có `reason`.
- Xuất JSON hợp lệ tại dòng cuối cùng của stdout.

##### 2. Signature & Kiểu Dữ Liệu Tham Số
```python
def emit_final(
    answer: Any,
    type: str,
    evidence: str,
    check: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None
) -> None:
```
- `answer`: Giá trị đáp án (số, chuỗi, boolean, list, dict dạng bảng, hoặc `None`).
- `type`: Kiểu dữ liệu (`"number"`, `"percent"`, `"string"`, `"date"`, `"boolean"`, `"list"`, `"table"`, `"unanswerable"`, `"abstain"`).
- `evidence`: Chuỗi mô tả ngắn gọn căn cứ tính toán (tên file, cột dữ liệu).
- `check` (`dict | None`): Đối tượng xác minh độ tin cậy gồm `{"rows_after_filter": int, "verified_zero": bool}`.
- `reason` (`str | None`): Lý do giải thích bắt buộc khi `type="unanswerable"`.

##### 3. Mã Nguồn Tham Khảo / Pseudo-code Chi Tiết
```python
def emit_final(answer, type, evidence, check=None, reason=None):
    clean_type = str(type).strip().lower()
    valid_types = ('number', 'percent', 'string', 'date', 'boolean', 'list', 'table', 'unanswerable', 'abstain')
    if clean_type not in valid_types:
        raise ValueError(f"Invalid answer type: {type!r}. Must be one of {valid_types}")

    # Chốt kiểm định tự động: Bẫy lọc rỗng
    if check and isinstance(check, dict):
        rows_filtered = check.get("rows_after_filter", None)
        if rows_filtered == 0 and not check.get("verified_zero", False):
            # Bộ lọc rỗng mà không được xác minh -> Chuyển sang abstain an toàn
            clean_type = "abstain"
            answer = None
            evidence = f"Auto-abstained: filter returned 0 rows ({evidence})"

    clean_answer = answer
    if clean_type in ('unanswerable', 'abstain'):
        clean_answer = None
    elif clean_type == 'number':
        clean_answer = round(float(answer), 2) if isinstance(answer, (int, float, np.number)) else parse_vn_number(answer)
    elif clean_type == 'percent':
        val = float(answer)
        if 0.0 < val <= 1.0:
            val = val * 100.0
        clean_answer = round(val, 2)
    elif clean_type == 'string':
        clean_answer = unicodedata.normalize('NFC', str(answer).strip())
    elif clean_type == 'date':
        clean_answer = pd.to_datetime(answer).strftime("%Y-%m-%d")
    elif clean_type == 'boolean':
        clean_answer = bool(answer)
    elif clean_type == 'list':
        if not isinstance(answer, list):
            clean_answer = [answer]
        clean_answer = [unicodedata.normalize('NFC', str(x).strip()) if isinstance(x, str) else x for x in clean_answer]
    elif clean_type == 'table':
        if not isinstance(answer, dict) or 'columns' not in answer or 'rows' not in answer:
            raise ValueError("Table answer must have 'columns' and 'rows'")
        clean_answer = answer

    payload = {
        "kind": "final",
        "type": clean_type,
        "answer": clean_answer,
        "evidence": str(evidence).strip() if evidence else "Computed via sandbox"
    }
    if check:
        payload["check"] = check
    if reason:
        payload["reason"] = str(reason).strip()

    print(json.dumps(payload, ensure_ascii=False, default=_default_json_enc))
```

### 2.3. Hướng Dẫn Tích Hợp Vào `src/agent/sandbox.py`

Khi thực thi mã do LLM sinh ra trong subprocess, toàn bộ 6 helper trên được đưa vào biến chuỗi `_SANDBOX_RUNTIME_HELPERS` (chèn trực tiếp vào phần đầu script Python tạm thời):
1. **Vị trí tích hợp**: Thay thế các hàm monkey-patching cũ tại dòng 417–795 của `src/agent/sandbox.py`.
2. **Namespace toàn cục**: Toàn bộ 6 helper xuất hiện trực tiếp trong namespace toàn cục (`globals()`), mã do mô hình sinh ra có thể gọi trực tiếp:
   ```python
   # Code mô hình sinh ra có thể gọi ngay:
   info = explore_data("SoBanHang.xlsx", column="Trạng thái")
   emit_obs(info, "Quan sát nhãn trạng thái")
   ```
3. **Loại bỏ Monkey-patching nguy hiểm**: Giữ lại các hàm tiện ích an toàn (`vn_norm`, `parse_vn_date`, `parse_vn_number`), loại bỏ hoàn toàn các monkey patch ghi đè lên toán tử so sánh `Series.__eq__` và `Series.sum`.

---

## 3. GIAO THỨC SUY LUẬN REACT, EPHEMERAL THINKING & THÍCH ỨNG LUẬT ĐỘNG

### 3.1. Giao Thức ReAct Tinh Gọn Đa Lượt

Để khắc phục hội chứng "Bẫy Một Lượt" (Turn-1 Exit Trap) khiến mô hình vội vã chốt đáp án sai, hệ thống triển khai chu trình **ReAct Tinh Gọn 2–3 Lượt** có định hướng mục tiêu con:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   CHU TRÌNH SUY LUẬN REACT TINH GỌN (MAX 2-3 TURNS)              │
├──────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│   [TURN 1: KHÁM PHÁ VÀ XÁC ĐỊNH PHẠM VI]                                         │
│   Thought: (3-5 dòng)                                                            │
│   - Plan: Cần tính doanh thu tháng 5/2026 cho shop biz_101.                       │
│   - Action: Dùng explore_data kiểm tra cột ngày và nhãn trạng thái thực tế.     │
│   - Target: Tránh bẫy lọc rỗng nhãn trạng thái.                                  │
│   Action:                                                                        │
│   ```python                                                                      │
│   st = explore_data("BanHang.csv", column="Trạng thái")                          │
│   emit_obs(st, "Kiểm tra nhãn trạng thái đơn")                                   │
│   ```                                                                            │
│                                    │                                             │
│                                    ▼                                             │
│   [SANDBOX EXECUTION] ─────────────┴──────────> Observation: Nhãn là 'Xong'      │
│                                    │                                             │
│                                    ▼                                             │
│   [TURN 2: TÍNH TOÁN VÀ CHỐT KẾT QUẢ]                                            │
│   Thought: (3-5 dòng)                                                            │
│   - Plan: Dữ liệu thực tế dùng nhãn 'Xong' (không phải 'hoàn thành').            │
│   - Action: Dùng load_clean_df đọc bảng, lọc Trạng thái == 'Xong', sum Doanh thu.│
│   - Check: rows_after_filter > 0.                                                │
│   Action:                                                                        │
│   ```python                                                                      │
│   df = load_clean_df("BanHang.csv", as_of_date=AS_OF_DATE)                       │
│   valid = df[df["Trạng thái"] == "Xong"]                                         │
│   d_range = resolve_date("tháng 5/2026")                                         │
│   ans = valid[(valid["Ngày"] >= d_range["start_date"]) &                         │
│               (valid["Ngày"] <= d_range["end_date"])]["Thành tiền"].sum()        │
│   emit_final(ans, type="number", evidence="BanHang.csv",                         │
│              check={"rows_after_filter": len(valid)})                            │
│   ```                                                                            │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

**Quy tắc điều phối bắt buộc**:
- `Thought:` khống chế nghiêm ngặt **3–5 dòng** (tập trung vào: Plan, Action, Check).
- Chặn đứng việc gọi helper thừa thãi: Mỗi turn chỉ gọi tối đa 1–2 helper.
- Giới hạn cứng số lượt: Mặc định `max_turns = 2` (hoặc tối đa 3 khi gặp lỗi cú pháp cần sửa). Điều này bảo đảm thời gian xử lý mỗi câu hỏi duy trì trong khoảng **8–15 giây**, tuyệt đối an toàn dưới trần 43.2 giây của Ban Tổ Chức.

---

### 3.2. Cơ Chế Ephemeral Thinking: Tối Ưu Cửa Sổ Ngữ Cảnh 16.384 Tokens

#### 1. Mô Hình Toán Học Bùng Nổ Token Ngữ Cảnh
Khi sử dụng các mô hình reasoning tiên tiến như `Qwen/Qwen2.5-14B-Instruct-1M`, mỗi lượt suy luận mô hình sinh ra một khối độc thoại nội tâm `<think>...</think>` rất dài:
- Ngữ cảnh khởi tạo ($T_0$): System Prompt (250) + Schema Profile (3.000) + User Prompt & Rules (2.250) = **5.500 tokens**.
- Khối `<think>` sinh ra trung bình: **2.000 tokens / turn**.
- Khối code Python sinh ra: **300 tokens / turn**.
- Dữ liệu Observation / Error traceback gửi lại: **500 tokens / turn**.
- Phụ phí ChatML: **50 tokens / turn**.

So sánh chi tiết tốc độ gia tăng ngữ cảnh giữa 2 phương án:
1. **Phương án Giữ Nguyên `<think>`**: Tích lũy $\Delta T = 2.000 + 300 + 500 + 50 = \mathbf{2.850\text{ tokens / turn}}$.
2. **Phương án Ephemeral Thinking (Cắt bỏ `<think>`, chỉ giữ tóm tắt 3–5 dòng)**: Tích lũy $\Delta T = 100 \text{ (Summary)} + 300 \text{ (Code)} + 500 \text{ (Obs)} + 50 = \mathbf{950\text{ tokens / turn}}$.

| Lượt (Turn) | Giữ Nguyên `<think>` (Context) | Ngân Sách Còn Lại | Trạng Thái Kỹ Thuật | Ephemeral Thinking (Context) | Ngân Sách Còn Lại | Trạng Thái Kỹ Thuật |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Turn 1** | 5.500 tok | 10.884 tok | Bình thường | 5.500 tok | 10.884 tok | Bình thường |
| **Turn 2** | 8.350 tok | 8.034 tok | Bình thường | 6.450 tok | 9.934 tok | Rất an toàn |
| **Turn 3** | 11.200 tok | 5.184 tok | Bắt đầu chậm | 7.400 tok | 8.984 tok | Rất an toàn |
| **Turn 4** | 14.050 tok | 2.334 tok | Cạn budget sinh | 8.350 tok | 8.034 tok | Rất an toàn |
| **Turn 5** | **16.900 tok** | **-516 tok** | **TRÀN CONTEXT (CRASH)** | 9.300 tok | 7.084 tok | Rất an toàn |
| **Turn 6** | 19.750 tok | -3.366 tok | Cắt xén mất prompt | 10.250 tok | 6.134 tok | Rất an toàn |
| **Turn 8** | 25.450 tok | -9.066 tok | Sập hệ thống | 12.150 tok | 4.234 tok | Rất an toàn |
| **Turn 10**| **31.150 tok** | **-14.766 tok**| **Vượt 190% bộ nhớ** | **14.050 tok** | **2.334 tok** | **VẪN AN TOÀN TUYỆT ĐỐI** |

#### 2. Nguy Cơ OOM và Phá Hủy Prefix Caching
- **Bộ nhớ KV-Cache**: Với mô hình 14B GQA (48 layers, 8 KV heads, dim 128, BF16), mỗi token chiếm $192\text{ KB}$. Ở context 16k, KV-Cache chiếm $3.0\text{ GB / sequence}$. Trọng số mô hình chiếm $29.4\text{ GB}$. Trên card RTX 5090 (32GB VRAM), nếu context phình to chạm trần 16k, GPU sẽ rơi vào trạng thái **CUDA Out-Of-Memory (OOM)** ngay lập tức.
- **Phá hủy Prefix Caching**: Khi context vượt giới hạn và hàm `_fit_messages_to_context()` cắt tỉa tin nhắn cũ, hàm băm token tiền tố thay đổi, **vô hiệu hóa hoàn toàn Automatic Prefix Caching (APC)** của vLLM, khiến độ trễ prefill tăng vọt gấp 3–4 lần.

#### 3. Thuật Toán Cài Đặt `prune_ephemeral_thinking` Trong `src/agent/solver.py`
Tại thời điểm chuyển giao giữa các turn (Turn $K \ge 2$), toàn bộ thẻ `<think>...</think>` thô của các Turn $1 \dots K-1$ được loại bỏ, chỉ giữ lại tóm tắt 3–5 dòng kế hoạch:

```python
def prune_ephemeral_thinking(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Lược bỏ toàn bộ khối <think> thô của các lượt assistant trước đó,
    chỉ lưu giữ tóm tắt kế hoạch 3-5 dòng + code thực thi để bảo toàn context window.
    """
    pruned_messages = []
    for i, msg in enumerate(messages):
        # Không sửa tin nhắn của system hoặc user
        if msg["role"] != "assistant":
            pruned_messages.append(msg)
            continue

        content = msg["content"]
        # Nếu là turn assistant cuối cùng và đang suy luận, giữ nguyên
        if i == len(messages) - 1:
            pruned_messages.append(msg)
            continue

        # Bóc tách khối <think>...</think>
        think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL | re.IGNORECASE)
        code = extract_python_code(content)
        
        thought_summary = ""
        if think_match:
            raw_think = think_match.group(1).strip()
            # Trích xuất các dòng định hướng kế hoạch nếu có
            plan_lines = [line.strip() for line in raw_think.splitlines() 
                          if line.strip().startswith(("-", "*", "Plan:", "Action:", "Step:", "Kế hoạch:"))]
            if plan_lines:
                thought_summary = "Thought Plan:\n" + "\n".join(plan_lines[:4])
            else:
                sentences = [s.strip() for s in re.split(r'[.\n]+', raw_think) if len(s.strip()) > 10]
                thought_summary = "Thought Plan:\n" + ". ".join(sentences[-3:]) + "."
        elif "Thought:" in content:
            thought_part = content.split("```")[0].strip()
            thought_summary = "\n".join(thought_part.splitlines()[:4])

        # Khống chế độ dài tóm tắt dưới 350 ký tự (~60 tokens)
        if len(thought_summary) > 350:
            thought_summary = thought_summary[:350] + "..."

        if code:
            compact_content = f"{thought_summary}\n\n```python\n{code}\n```".strip()
        else:
            clean_text = content.split("</think>", 1)[-1].strip() if "</think>" in content else content
            compact_content = clean_text[:500]

        pruned_messages.append({
            "role": "assistant",
            "content": compact_content
        })

    return pruned_messages
```

---

### 3.3. Cơ Chế Thích Ứng Luật Động (Dynamic In-Context Rule Extraction)

#### 1. Vấn Đề Biến Động Ngành Nghề Giữa Các Phân Vùng Dữ Liệu
- **Tập Train**: Gồm 30 shop thuộc 3 ngành: F&B / Cà phê, Tạp hóa / Bán lẻ, Vật liệu xây dựng, Nhà thuốc.
- **Tập Public Test**: Bổ sung thêm **3 ngành nghề hoàn toàn mới**:
  1. *Mẹ và bé* (`dev_010`, `dev_013`): Quy ước dòng Voucher/Điểm ghi số âm nhưng trả về số dương; Tỉ lệ bỉm chia cho tổng số bịch tã bỉm trong kỳ.
  2. *Sửa xe máy* (`dev_004`, `dev_012`): Phiếu bảo hành 0đ vẫn tính là 1 lượt xe; Khách quen xác định qua **biển số xe** (từ 2 phiếu có thu tiền).
  3. *Cửa hàng điện thoại* (`dev_007`, `dev_008`, `dev_011`, `dev_014`): Thu máy cũ không trừ vào doanh thu; Dòng máy lấy trước dung lượng `GB` (iPhone 13 128GB $\to$ iPhone 13); Hãng là Apple đối với iPhone.
- **Tập Private Test**: Chắc chắn xuất hiện các ngành nghề chưa từng thấy (Salon tóc, Tiệm giặt ủi, Spa thú cưng, Phòng gym...).

#### 2. Cơ Chế Nạp Động Ngữ Cảnh Runtime
Tuyệt đối không được hardcode tên cột hay luật ngành vào code Python. Hệ thống áp dụng cơ chế nạp động:
1. **Nạp `rulebook.md` của split hiện tại**: Khi container khởi chạy trên máy chủ chấm điểm, đối tượng `shared_context` tự động đọc file `rulebook.md` nằm trong thư mục dữ liệu được mount (`/data/rulebook.md`).
2. **Nạp `README.md` của từng shop**: Trước mỗi câu hỏi, hệ thống đọc file `README.md` của shop đó để nắm bắt quy ước riêng (đơn vị tính, cột trạng thái, phân loại khách hàng).
3. **Áp Dụng Nguyên Tắc Chặn Theo Rulebook §7**:
   > *"Nếu một khái niệm, thực thể, hoặc trường dữ liệu trong câu hỏi hoàn toàn không xuất hiện trong các bảng dữ liệu và không được định nghĩa trong README.md hoặc rulebook.md $\to$ BẮT BUỘC PHẢI TỪ CHỐI TRẢ LỜI (`"abstain"` hoặc `"unanswerable"`)."*

Quy tắc này giúp Agent hoàn toàn miễn nhiễm trước các câu hỏi "bẫy" suy đoán vô căn cứ trên các ngành nghề mới.

---

## 4. CƠ CHẾ CỔNG ABSTAIN-FIRST GATE & XỬ LÝ LỖI THỰC NGHIỆM

### 4.1. Pháp Y 4 Mẫu Lỗi Chí Mạng Trên Bộ 30 Dev Benchmark

Khảo sát thực nghiệm đối chứng trên bộ 30 câu Unseen Dev benchmark giữa Base Model và Base + LoRA cũ cho thấy:
- **Pretrained Base**: 7 Đúng, 12 Sai, 11 Abstain $\to \mathbf{\text{PA} = -0.1667}$.
- **Base + LoRA Cũ**: 7 Đúng, 9 Sai, 14 Abstain $\to \mathbf{\text{PA} = -0.0667}$.

Toàn bộ 9–12 câu bị phạt điểm âm bắt nguồn từ 4 mẫu lỗi chí mạng:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   4 MẪU LỖI CHÍ MẠNG GÂY ĐIỂM PHẠT PA ÂM TRÊN DEV-30             │
├──────────────────────────┬───────────────────────────────────────────────────────┤
│ Mẫu Lỗi                  │ Cơ Chế Phát Sinh & Hậu Quả                            │
├──────────────────────────┼───────────────────────────────────────────────────────┤
│ 1. Empty Filter Trap     │ Lọc chuỗi cứng '.str.contains("hoàn thành")' làm rỗng │
│    (Bẫy lọc rỗng)        │ bảng về 0 dòng -> .sum() ra 0 hoặc sinh đáp án bừa.   │
├──────────────────────────┼───────────────────────────────────────────────────────┤
│ 2. Entity Mismatch       │ Tên sản phẩm không dấu 'soda chanh day' != 'Soda      │
│    (Lệch tên thực thể)   │ chanh dây (M)' -> so khớp chính xác == ra 0 dòng.    │
├──────────────────────────┼───────────────────────────────────────────────────────┤
│ 3. Zero Unverified       │ Không có dữ liệu tính ra 0đ hoặc 0% rồi chốt luôn mà  │
│    (Số 0 chưa kiểm chứng)│ không có bằng chứng chứng minh dữ liệu tồn tại.       │
├──────────────────────────┼───────────────────────────────────────────────────────┤
│ 4. Out-of-Scope          │ Shop không có file kho / địa chỉ nhưng mô hình tự     │
│    (Ảo giác ngoài phạm vi│ bịa số liệu thay vì áp dụng Rulebook §7 để từ chối.   │
└──────────────────────────┴───────────────────────────────────────────────────────┘
```

---

### 4.2. Bảng Phân Tích Chi Tiết Các Câu Hỏi Bị Sai Phạt Điểm Nặng

Dưới đây là bảng pháp y chi tiết từng câu hỏi bị sai trên bộ benchmark Dev-30:

| Mã Câu Hỏi | Shop ID | Nội Dung Câu Hỏi | Hành Vi Sai Lầm Của Agent Cũ | Hậu Quả PA | Giải Pháp Triệt Để Với Kiến Trúc Mới |
|---|---|---|---|:---:|---|
| `q_20aa992c0d3f` | `biz_101` | Tháng 5/2026 ngày nào cửa hàng bán được nhiều tiền nhất? | Shop dùng nhãn `Xong`, model lọc `"hoàn thành"` $\to$ rỗng 0 dòng. Turn 3 hallucinate chốt bừa `"2026-05-01"` với doanh thu 0đ. | **-1.0** | Dùng `explore_data(file, column="Trạng thái")` phát hiện nhãn `Xong` $\to$ Tính chuẩn ngày `"2026-05-09"` (**+1.0**). |
| `q_554d736852a5` | `biz_111` | Tổng doanh thu đơn hoàn thành tháng 4/2026? | Shop dùng nhãn `completed`, model lọc `"hoàn thành"` $\to$ ra 0đ. | **-1.0** | `explore_data` phát hiện nhãn `completed` $\to$ Tính chuẩn `70017` (**+1.0**). |
| `q_7428165a9e0a` | `biz_129` | Tổng doanh thu hôm qua là bao nhiêu? | 47 đơn ngày hôm qua mang nhãn `completed`. Model lọc `"hoàn thành"` $\to$ 0 dòng $\to$ trả về 0đ. | **-1.0** | Helper `load_clean_df` tự động xử lý trạng thái hoặc `explore_data` phát hiện nhãn $\to$ Tính đúng `22740500` (**+1.0**). |
| `q_01a28f2233bd` | `biz_112` | Giá bán một ly soda chanh day (m) vào ngày 01/12/2025 là bn? | So sánh `df["Tên"] == "Soda chanh day (M)"` không khớp do thiếu dấu tiếng Việt $\to$ Crash. | **-1.0** | Helper `fuzzy_find` xóa dấu `vn_norm` tìm ra ngay `"Soda chanh dây (M)"` với giá `37000` (**+1.0**). |
| `q_95099c4916a8` | `biz_109` | Khách nữ chiếm bao nhiêu % doanh thu tháng 12/2025? | Shop chỉ có loại khách `Cá nhân` (không có cột giới tính). Model lọc từ "nữ" ra 0 dòng $\to$ chốt `0.0%`. | **-1.0** | Cổng Kiểm duyệt Cổng 1 & Cổng 3 phát hiện thiếu cột giới tính $\to$ Kích hoạt Rulebook §7 trả về `"abstain"` (**0.0**). |
| `q_fcafb39ec35f` | `biz_109` | Khách đường Lê Trọng Tấn và khách đường Trần Não bên nào mua nhiều hơn? | Shop không có cột địa chỉ đường phố. Model tìm tên đường trong tên khách $\to$ ra 2 tập rỗng $\to$ kết luận bằng nhau. | **-1.0** | Cổng Kiểm duyệt Cổng 1 phát hiện thiếu cột địa chỉ $\to$ Chuyển `"abstain"` (**0.0**). |
| `q_22f59bab1075` | `biz_112` | Hết hôm nay trong kho còn bao nhiêu hộp Bánh croissant? | Shop không có file kho. Model lấy cột cấu hình trần `Tồn lớn nhất = 999.999.999` chia 6 $\to$ in đáp án `[166666666, 3]`! | **-1.0** | Cổng Kiểm duyệt Cổng 1 phát hiện shop không có dữ liệu kho $\to$ Chuyển `"abstain"` (**0.0**). |
| `q_d401c0884402` | `biz_130` | So với cùng kỳ tháng trước, doanh thu tăng hay giảm bao nhiêu %? | Prompt cũ tiêm khoảng cả tháng trước, model lấy cả tháng 7 so với 3 ngày đầu tháng 8 $\to$ Lệch số. | **-1.0** | Helper `resolve_date("cùng kỳ tháng trước")` tính đúng từ 01/07 đến 03/07 $\to$ Tính chuẩn (**+1.0**). |

---

### 4.3. Kiến Trúc Cổng Kiểm Duyệt Đa Tầng (Multi-Layer Abstain Gate)

Để triệt tiêu toàn bộ điểm phạt $-1.0$, hệ thống triển khai Cổng Kiểm duyệt 4 tầng bảo vệ:

```
[MÃ NGUỒN SINH RA / KẾT QUẢ THỰC THI SANDBOX]
                       │
                       ▼
          ┌─────────────────────────┐
          │ CỔNG 1: SCHEMA CHECK    │ ──> Thiếu bảng kho/nợ? Thiếu cột giới tính/địa chỉ?
          │ (Rulebook Section 7)    │     ==> CHUYỂN NGAY SANG "ABSTAIN" (0.0 PT)
          └─────────────────────────┘
                       │
                       ▼
          ┌─────────────────────────┐
          │ CỔNG 2: EMPTY FILTER    │ ──> rows_after_filter == 0 sau khi lọc chuỗi?
          │ (Zero-Row Interceptor)  │     ==> YÊU CẦU UNIQUE()/FUZZY; HẾT LƯỢT -> "ABSTAIN"
          └─────────────────────────┘
                       │
                       ▼
          ┌─────────────────────────┐
          │ CỔNG 3: ZERO SANITY     │ ──> Doanh thu = 0đ, Tỉ lệ = 0%, Bảng nợ toàn 0?
          │ (Unverified Zero Check) │     ==> THIẾU VERIFIED_ZERO -> "ABSTAIN" (0.0 PT)
          └─────────────────────────┘
                       │
                       ▼
          ┌─────────────────────────┐
          │ CỔNG 4: RETRY BUDGET    │ ──> SyntaxError / Timeout sau 2 lượt sửa?
          │ (Execution Exhaustion)  │     ==> CHUYỂN KHẨN CẤP SANG "ABSTAIN" (0.0 PT)
          └─────────────────────────┘
                       │
                       ▼
         [SUBMISSION AN TOÀN TUYỆT ĐỐI]
```

1. **Cổng 1: Schema/Entity Absence Check (Rulebook §7)**:
   Trước khi thực hiện tính toán, kiểm tra xem câu hỏi có chứa các thực thể ngoài phạm vi dữ liệu hay không (giới tính, địa chỉ đường phố, lý do hủy đơn, hướng dẫn y tế). Nếu shop không có bảng hoặc cột tương ứng, lập tức kích hoạt `"abstain"`.
2. **Cổng 2: Empty Filter Intercept (Chặn Bẫy Lọc Rỗng)**:
   Nếu phép lọc trên DataFrame trả về 0 dòng (`rows_after_filter == 0`):
   - Ở Turn 1: Trả về observation cảnh báo mô hình dùng `fuzzy_find` hoặc `explore_data(..., column=...)` để lấy nhãn thực tế.
   - Ở Turn 2+: Tuyệt đối cấm chốt kết quả bằng 0 hoặc rỗng; tự động ép kết quả sang `"abstain"`.
3. **Cổng 3: Zero-Sanity Verification (Kiểm Định Kết Quả Bằng 0)**:
   Đối với các chỉ số doanh thu, tiền nợ, số lượng bán, nếu kết quả tính ra bằng `0` mà không kèm theo cờ `verified_zero=True` (chứng minh có phát sinh dòng giao dịch nhưng giá trị bằng 0), hệ thống tự động hoán đổi đáp án thành `"abstain"`.
4. **Cổng 4: Execution Failure & Retry Budget Exhaustion**:
   Nếu sau 2 lượt ReAct mà code vẫn gặp lỗi runtime (`SyntaxError`, `KeyError`, `IndexError`) hoặc `TimeoutExpired`, hệ thống tự động emit `"abstain"` (nhận 0.0 điểm) thay vì để chương trình ném Exception làm hỏng định dạng file nộp bài.

---

## 5. HƯỚNG DẪN ĐÁNH GIÁ TRÊN GOOGLE COLAB & TINH CHỈNH LORA

### 5.1. Khẳng Định Nền Tảng Mô Hình `Qwen/Qwen2.5-14B-Instruct-1M`

Dự án giữ nguyên mô hình mục tiêu **`Qwen/Qwen2.5-14B-Instruct-1M`** (hoặc biến thể `Qwen2.5-Coder-14B-Instruct`):
- **Tuân thủ Thể lệ Rule 2**: Tổng số tham số là **$14.7\text{B} \le 15\text{B}$**.
- **Cân bằng Hoàn hảo**: Là kích thước tối ưu nhất giữa năng lực sinh code Python phức tạp, suy luận bảng biểu và tốc độ suy luận trên GPU máy chủ BTC ($2 \times \text{RTX 5090}$).
- **Tương thích vLLM & Docker**: Hỗ trợ đầy đủ FlashAttention-2, PagedAttention và giao thức inference offline `--network none`.

---

### 5.2. Quy Trình Đánh Giá Trên Colab (`Evaluate_Qwen25_14B_1M_Colab_G4.ipynb`)

Notebook `notebooks/Evaluate_Qwen25_14B_1M_Colab_G4.ipynb` được thiết kế để thẩm định độc lập mô hình trên nền tảng Google Colab (các tier GPU: A100 80GB/40GB, L4 24GB, hoặc T4 16GB). Lập trình viên triển khai thực hiện theo 4 bước chuẩn:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   QUY TRÌNH 4 BƯỚC THẨM ĐỊNH TRÊN GOOGLE COLAB                   │
├──────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  [BƯỚC 1: THIẾT LẬP MÔI TRƯỜNG & CHỌN PROFILE GPU]                               │
│  - Chạy Cell 1 & 2 kiểm tra CUDA 12.8, capability, VRAM.                         │
│  - Tự động nhận diện GPU Profile:                                                │
│    * A100 80GB (Tier G4): bfloat16, ctx=16384, max_tokens=4096, max_seqs=16.    │
│    * A100 40GB: bfloat16, ctx=16384, max_tokens=4096, max_seqs=2.               │
│    * L4 24GB: float16, load_in_4bit=True, ctx=12288, max_seqs=2.                │
│                                    │                                             │
│                                    ▼                                             │
│  [BƯỚC 2: PHẪU THUẬT CẤU HÌNH (CONFIG SURGERY)]                                  │
│  - Gỡ bỏ 'dual_chunk_attention_config' trong config.json của model local.        │
│  - Xóa file 'sparse_attention_config.json'.                                      │
│  - Chuyển sang Dense Full Attention để chạy ổn định vLLM + LoRA ở ctx 16k.       │
│                                    │                                             │
│                                    ▼                                             │
│  [BƯỚC 3: NẠP ĐÈ MÃ NGUỒN MỚI (CODE OVERLAY ZIP)]                                │
│  - Đóng gói code cập nhật: python scripts/package_and_upload_bundle.py --overlay-only│
│  - Upload 'datamate_eval_code_overlay.zip' lên Colab (/content/).                │
│  - Notebook tự động giải nén đè vào src/agent/sandbox.py và solver.py.           │
│                                    │                                             │
│                                    ▼                                             │
│  [BƯỚC 4: SUY LUẬN TẤT ĐỊNH & KIỂM TRA SUBMISSION + LOGS]                        │
│  - Chạy suy luận với seed=42, temperature=0.0 (Rule 5).                          │
│  - Kiểm tra file submission.jsonl và logs chi tiết tại /result/logs/<qid>.json.  │
│  - Xác thực điểm số PA và xuất comparison.json đối chứng Base vs LoRA.           │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

#### Chi Tiết Thao Tác Kỹ Thuật Bước 2: Config Surgery
```python
# Đoạn code thực thi tại Cell 3 của Notebook:
cfg_path = LOCAL_MODEL_DIR / 'config.json'
cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
if cfg.pop('dual_chunk_attention_config', None) is not None:
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')
    print('🔧 Đã gỡ dual_chunk_attention_config trong config.json.')

sparse_cfg = LOCAL_MODEL_DIR / 'sparse_attention_config.json'
if sparse_cfg.exists():
    sparse_cfg.unlink()
    print('🔧 Đã xóa sparse_attention_config.json.')
```

---

### 5.3. Chuẩn Hóa Bộ Dữ Liệu Huấn Luyện SFT & Cấu Hình LoRA

#### 1. Cảnh Báo Nghiêm Cấm Sử Dụng Dataset SFT Cũ (Code-Only)
Bộ dữ liệu SFT 817 mẫu cũ chỉ chứa mã Python nguyên khối mà không có chuỗi suy luận ReAct. Điều này gây ra 3 hậu quả nghiêm trọng:
- Mô hình học vẹt đoạn mã `.str.contains("hoàn thành")`, tự hủy khi gặp nhãn `Xong`.
- Mô hình bị bẫy "One-shot exit", luôn chốt ở Turn 1 mà không bao giờ gọi các lệnh khám phá bảng.
- Mô hình không biết cách từ chối khi gặp câu hỏi thiếu dữ liệu.

#### 2. Cấu Trúc JSONL Của Bộ Dữ Liệu SFT ReAct Mới
Tệp dữ liệu huấn luyện `sft_react_trajectories.jsonl` phải được định dạng chuẩn ChatML đa lượt:

```json
{
  "id": "train_biz101_q001",
  "business_id": "biz_101",
  "messages": [
    {
      "role": "system",
      "content": "<Toàn văn Rulebook chung + Hướng dẫn 6 Lean Helpers + Giao thức JSON>"
    },
    {
      "role": "user",
      "content": "Câu hỏi: Tháng 5/2026 ngày nào bán được nhiều tiền nhất?\nas_of_date: 2026-05-31\nFiles: BanHang.csv\nREADME:\n..."
    },
    {
      "role": "assistant",
      "content": "Thought:\n- Plan: Khám phá nhãn trạng thái đơn trong BanHang.csv để tránh lọc rỗng.\n- Action: Gọi explore_data trên cột Trạng thái.\n\n```python\nres = explore_data('BanHang.csv', column='Trạng thái')\nemit_obs(res, 'Kiểm tra nhãn trạng thái')\n```"
    },
    {
      "role": "user",
      "content": "{\"kind\": \"observation\", \"data\": {\"unique_values\": [\"Xong\", \"Hủy\"]}, \"message\": \"Kiểm tra nhãn trạng thái\"}"
    },
    {
      "role": "assistant",
      "content": "Thought:\n- Plan: Nhãn trạng thái hợp lệ là 'Xong'. Lọc dữ liệu tháng 5/2026, nhóm theo ngày và tính tổng tiền.\n- Check: rows_after_filter > 0 trước khi emit_final.\n\n```python\ndf = load_clean_df('BanHang.csv', as_of_date='2026-05-31')\nvalid = df[df['Trạng thái'] == 'Xong'].copy()\nvalid['Ngày'] = pd.to_datetime(valid['Ngày'])\nm5 = valid[(valid['Ngày'] >= '2026-05-01') & (valid['Ngày'] <= '2026-05-31')]\ndaily = m5.groupby(m5['Ngày'].dt.strftime('%Y-%m-%d'))['Thành tiền'].sum()\ntop_day = daily.idxmax()\nemit_final(top_day, type='date', evidence='BanHang.csv', check={'rows_after_filter': len(m5)})\n```"
    }
  ]
}
```

#### 3. Tham Số Siêu Tinh Chỉnh LoRA Khuyến Nghị (PEFT Configuration)
- **Target Modules**: `["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]` (toàn bộ các lớp Linear).
- **LoRA Rank ($r$)**: `16` (hoặc `32` nếu đủ VRAM).
- **LoRA Alpha ($\alpha$)**: `32` (hoặc `64`, tỉ lệ $\alpha / r = 2.0$).
- **LoRA Dropout**: `0.05`.
- **Learning Rate**: `1e-4` với cosine learning rate scheduler, warmup ratio `0.03`.
- **Batch Size & Gradient Accumulation**: Effective batch size = `16`.
- **Max Sequence Length**: `4096` tokens trong quá trình huấn luyện SFT.

---

## 6. KẾ HOẠCH BÀN GIAO & PHÂN BỔ CÔNG VIỆC TRIỂN KHAI (ROADMAP)

### 6.1. Phân Rã Các Gói Nhiệm Vụ Kỹ Thuật (Work Breakdown Structure)

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   LỘ TRÌNH 4 GÓI NHIỆM VỤ TRIỂN KHAI CHO DEVELOPER               │
├──────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  [TASK 1: REFACTOR SANDBOX VỚI 6 LEAN HELPERS]                                   │
│  - File phụ trách: src/agent/sandbox.py                                          │
│  - Xóa bỏ monkey-patching ngầm cũ.                                               │
│  - Cài đặt chuẩn hóa: explore_data, fuzzy_find, load_clean_df, resolve_date,      │
│    emit_obs, emit_final.                                                         │
│  - Viết unit test kiểm thử độc lập 6 helper trong tests/test_lean_helpers.py.    │
│                                    │                                             │
│                                    ▼                                             │
│  [TASK 2: CẬP NHẬT SOLVER VỚI EPHEMERAL THINKING & DYNAMIC RULE]                 │
│  - File phụ trách: src/agent/solver.py, src/agent/prompts.py                     │
│  - Cài đặt hàm prune_ephemeral_thinking() để bóc tách <think> ở Turn >= 2.       │
│  - Cập nhật prompts.py: Nạp động rulebook runtime và README shop vào prompt.     │
│  - Khống chế max_turns = 2 (tối đa 3).                                           │
│                                    │                                             │
│                                    ▼                                             │
│  [TASK 3: TÍCH HỢP CỔNG KIỂM DUYỆT ABSTAIN-FIRST GATE]                           │
│  - File phụ trách: src/agent/solver.py, src/agent/runner.py                      │
│  - Nâng cấp hàm _eval_guard_issue(): Chặn bẫy lọc rỗng, chặn zero unverified,    │
│    chặn unanswerable không có căn cứ.                                            │
│  - Cài đặt fallback khẩn cấp sang "abstain" khi hết lượt retry hoặc timeout.     │
│                                    │                                             │
│                                    ▼                                             │
│  [TASK 4: VALIDATION TRÊN COLAB & XÂY DỰNG DATASET SFT REACT]                    │
│  - File phụ trách: notebooks/Evaluate_Qwen25_14B_1M_Colab_G4.ipynb, scripts/     │
│  - Đóng gói datamate_eval_code_overlay.zip và chạy benchmark 30 câu trên Colab.  │
│  - Xác thực PA tăng từ -0.0667 lên >= +0.4000.                                   │
│  - Tạo dataset SFT ReAct mới (sft_react_trajectories.jsonl) và fine-tune LoRA.   │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

### 6.2. Tiêu Chí Nghiệm Thu Kỹ Thuật Bắt Buộc (Acceptance Criteria)

Lập trình viên nhận bàn giao phải đảm bảo giải pháp thỏa mãn 100% các tiêu chí nghiệm thu sau trước khi nghiệm thu hoàn tất:

1. **Tính Đúng Đắn & Độc Lập Của 6 Lean Helpers**:
   - Chạy toàn bộ test suites trong `tests/` với kết quả 100% Pass.
   - `explore_data` xử lý trơn tru cả CSV, Excel nhiều sheet, và SQLite.
   - `fuzzy_find` so khớp chuẩn xác tên sản phẩm không dấu với độ chính xác $\ge 95\%$.
   - `load_clean_df` unmerge thành công và khử trùng lặp đơn hàng theo Rulebook §8 mà không làm rò rỉ đơn của khách lẻ.
   - `resolve_date` tính đúng 100% các mốc ngày âm lịch/Tết và kẹp ngày cuối tháng.
2. **Hiệu Quả Bảo Toàn Ngữ Cảnh Của Ephemeral Thinking**:
   - Trong quá trình chạy multi-turn (tới Turn 3), tổng độ dài `messages` không bao giờ vượt quá **8.000 tokens** (vẫn còn $> 50\%$ khoảng trống của cửa sổ 16.384).
   - Không xuất hiện bất kỳ ngoại lệ CUDA OOM nào trên phần cứng kiểm thử.
3. **Tiêu Chí Triệt Tiêu Điểm Phạt Của Abstain-First Gate**:
   - Khi chạy trên tập 30 Dev benchmark, số câu trả lời sai bị phạt ($-1.0$) phải giảm từ 9–12 câu xuống **$\le 2$ câu**.
   - Mọi câu hỏi thuộc nhóm `unanswerable` do thiếu cột thông tin (giới tính, địa chỉ, kho) phải được nhận diện và trả về `"abstain"` (nhận 0.0 điểm) thay vì đoán mò số liệu.
4. **Chỉ Số Điểm Số Penalized Accuracy Mục Tiêu**:
   - Điểm số Penalized Accuracy trên bộ 30 Unseen Dev benchmark đạt **$\text{PA} \ge \mathbf{+0.4000}$** (tối thiểu 14–16 câu đúng, $\le 2$ câu sai, còn lại là abstain an toàn).
5. **Tuân Thủ Thể Lệ Docker & Thời Gian**:
   - Thời gian suy luận trung bình mỗi câu hỏi trên GPU server $\le 15\text{ giây}$.
   - Container Docker đóng gói chạy hoàn toàn offline (`--network none`), mount thư mục `/data:ro` không phát sinh bất kỳ lỗi ghi đĩa nào.
   - Định dạng file `result/submission.jsonl` và các file logs `result/logs/<question_id>.json` tuân thủ 100% quy định Ban Tổ Chức.

---
*Tài liệu Kế hoạch Bàn giao Kỹ thuật được phê duyệt và lưu hành nội bộ tại repository Zalo AI Challenge 2026: DataMate.*
