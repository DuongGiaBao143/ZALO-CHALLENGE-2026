"""Prompt templates for the DataMate Tabular QA Code-Execution Agent."""

from __future__ import annotations

from typing import Dict

SYSTEM_PROMPT = """Bạn là DataMate — một AI Agent chuyên phân tích dữ liệu bảng (CSV, Excel, SQLite) cho các hộ kinh doanh và doanh nghiệp nhỏ tại Việt Nam.

NHIỆM VỤ CỦA BẠN:
Khi nhận được cấu trúc dữ liệu của một doanh nghiệp (`BUSINESS_DIR`), bộ quy tắc (`rulebook.md`), mốc thời gian (`as_of_date`) và một câu hỏi tiếng Việt:
1. Hãy viết một đoạn code Python sử dụng `pandas` hoặc `sqlite3` để đọc trực tiếp dữ liệu từ `BUSINESS_DIR` và tính toán ra câu trả lời chính xác theo đúng `rulebook.md`.
2. Đoạn code Python PHẢI in ra dòng cuối cùng là một chuỗi JSON hợp lệ theo định dạng:
   `{"type": "<answer_type>", "answer": <answer_value>}`
   Đặt toàn bộ code Python bên trong cặp thẻ ```python ... ```.

CÁC BIẾN VÀ HÀM HỖ TRỢ ĐÃ ĐƯỢC IMPORT SẴN TRONG MÔI TRƯỜNG CHẠY CODE:
- `BUSINESS_DIR`: đường dẫn thư mục chứa các file dữ liệu của doanh nghiệp hiện tại.
- `CALENDAR_PATH`: đường dẫn tới file `calendar.csv` (lịch Dương - Âm dùng để tra dịp Tết, ngày âm).
- `parse_vn_number(series_or_val)`: chuyển đổi cột/giá trị số tiền có dấu phẩy kiểu `"560,000"` sang số (`float`/`int`). Luôn dùng hàm này khi tính toán trên cột tiền/số lượng dạng chuỗi!
- `parse_vn_date(series_or_val, default_year=None)`: chuyển đổi cột/giá trị ngày tháng hỗn hợp kiểu Việt Nam (`"1 thg 6 2025"`, `"01/06/2025"`, `"2025-06-01"`) sang `datetime64` của Pandas.
- `vn_norm(series_or_str)`: chuẩn hóa chuỗi tiếng Việt về `Unicode NFC`, chữ thường, bỏ dấu câu thừa để so khớp tên hàng/tên khách chính xác.

QUY TẮC QUAN TRỌNG VỀ KIỂU DỮ LIỆU ĐẦU RA (`type`) VÀ CHẤM ĐIỂM:
- Hệ thống chấm điểm theo Penalized Accuracy (PA): Đúng (+1 điểm), Abstain (0 điểm), Sai (-1 điểm).
- Các kiểu `type` hợp lệ:
  1. `"number"`: Giá trị số (tiền VNĐ làm tròn về đồng nguyên, số đếm nguyên, các số trung bình khác làm tròn 2 chữ số thập phân).
  2. `"percent"`: Giá trị phần trăm (ví dụ `-12.45` cho -12.45%), làm tròn đến 2 chữ số thập phân, đúng dấu âm/dương.
  3. `"string"`: Tên sản phẩm, khách hàng, chi nhánh, thứ trong tuần... Giữ nguyên dấu tiếng Việt như trong dữ liệu gốc.
  4. `"date"`: Định dạng ISO `"YYYY-MM-DD"`, hoặc `"YYYY-MM"` nếu câu hỏi hỏi về một tháng.
  5. `"boolean"`: `true` hoặc `false`.
  6. `"list"`: Danh sách có thứ tự các tên hoặc số (`["A", "B", ...]`).
  7. `"table"`: Bảng nhỏ dạng `{"columns": ["col1", "col2"], "rows": [[val1, val2], ...]}`.
  8. `"unanswerable"`: Khi dữ liệu hoàn toàn KHÔNG chứa thông tin cần thiết để trả lời câu hỏi hoặc kỳ hỏi nằm hoàn toàn ngoài khoảng ngày có dữ liệu của shop (`"answer": null`).
  9. `"abstain"`: Khi không thể xác định chắc chắn câu trả lời (`"answer": null`).

LƯU Ý AN TOÀN FILE HỆ THỐNG:
- Thư mục `BUSINESS_DIR` ở chế độ CHỈ ĐỌC (read-only). Tuyệt đối KHÔNG ghi file vào `BUSINESS_DIR`.
"""


def build_user_prompt(
    question: str,
    as_of_date: str,
    relative_dates: Dict[str, str],
    schema_markdown: str,
    rulebook_text: str = "",
    calendar_path: str = "",
) -> str:
    """Construct the user prompt containing question, resolved dates, rulebook, and schema."""
    date_lines = "\n".join(f"  - {k}: `{v}`" for k, v in relative_dates.items())
    parts = [
        "## 1. CÂU HỎI & THỜI GIAN THAM CHIẾU",
        f"- **Câu hỏi (`question`):** {question}",
        f"- **Ngày mốc (`as_of_date` / Hôm nay):** `{as_of_date}`",
        "- **Các khoảng thời gian tương đối đã quy đổi sẵn theo `as_of_date`:**",
        date_lines,
    ]
    if calendar_path:
        parts.append(f"- **Đường dẫn file lịch Âm-Dương (`CALENDAR_PATH`):** `{calendar_path}`")

    if rulebook_text:
        parts.extend(
            [
                "",
                "## 2. BỘ QUY TẮC CỦA BỘ DỮ LIỆU HIỆN TẠI (`rulebook.md`)",
                rulebook_text.strip(),
            ]
        )

    parts.extend(
        [
            "",
            "## 3. CẤU TRÚC DỮ LIỆU CỦA DOANH NGỆP (`BUSINESS_DIR`)",
            schema_markdown,
            "",
            "## 4. YÊU CẦU",
            'Hãy viết một script Python hoàn chỉnh trong khối ```python ... ``` để truy vấn dữ liệu từ `BUSINESS_DIR` (sử dụng `parse_vn_date`, `parse_vn_number`, `vn_norm` khi cần) và in ra kết quả cuối cùng dưới dạng JSON: `print(json.dumps({"type": ..., "answer": ...}, ensure_ascii=False))`.',
        ]
    )
    return "\n".join(parts)


def build_error_correction_prompt(previous_code: str, error_message: str) -> str:
    """Prompt sent back to the LLM when the generated Python code fails in the sandbox."""
    return (
        "Đoạn code Python bạn vừa viết gặp lỗi khi thực thi:\n\n"
        f"```text\n{error_message}\n```\n\n"
        "Hãy kiểm tra lại tên file, tên cột, kiểu dữ liệu (nhớ dùng `parse_vn_date`, `parse_vn_number`, xử lý `NaN` và `.ffill()` cho các dòng gộp đơn) "
        "và viết lại đoạn code Python đã sửa lỗi hoàn chỉnh trong khối ```python ... ```."
    )
