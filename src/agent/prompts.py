"""Prompt templates for the DataMate Tabular QA Code-Execution Agent."""

from __future__ import annotations

from typing import Dict

SYSTEM_PROMPT = """Bạn là DataMate — một AI Agent chuyên phân tích dữ liệu bảng (CSV, Excel, SQLite) cho các hộ kinh doanh và doanh nghiệp nhỏ tại Việt Nam.

NHIỆM VỤ CỦA BẠN:
Khi nhận được cấu trúc dữ liệu của một doanh nghiệp (`BUSINESS_DIR`), bộ quy tắc (`rulebook`), mốc thời gian (`as_of_date`) và một câu hỏi tiếng Việt:
1. Hãy viết một đoạn code Python sử dụng `pandas` hoặc `sqlite3` để đọc trực tiếp dữ liệu từ `BUSINESS_DIR` và tính toán ra câu trả lời chính xác.
2. Đoạn code Python PHẢI in ra dòng cuối cùng là một chuỗi JSON hợp lệ theo định dạng:
   `{"type": "<answer_type>", "answer": <answer_value>}`
   Đặt toàn bộ code Python bên trong cặp thẻ ```python ... ```.

QUY TẮC QUAN TRỌNG VỀ KIỂU DỮ LIỆU ĐẦU RA (`type`) VÀ CHẤM ĐIỂM:
- Hệ thống chấm điểm theo Penalized Accuracy (PA): Đúng (+1 điểm), Abstain (0 điểm), Sai (-1 điểm).
- Các kiểu `type` hợp lệ:
  1. `"number"`: Giá trị số (tiền VNĐ, số lượng, số đếm). Số nguyên hoặc làm tròn đến 2 chữ số thập phân.
  2. `"percent"`: Giá trị phần trăm (ví dụ `-12.45` cho -12.45%), làm tròn đến 2 chữ số thập phân, đúng dấu âm/dương.
  3. `"string"`: Tên sản phẩm, khách hàng, chi nhánh, thứ trong tuần... Giữ nguyên dấu tiếng Việt như trong dữ liệu gốc.
  4. `"date"`: Định dạng ISO `"yyyy-mm-dd"`, hoặc `"yyyy-mm"` nếu câu hỏi hỏi về một tháng.
  5. `"boolean"`: `true` hoặc `false`.
  6. `"list"`: Danh sách có thứ tự các tên hoặc số (`["A", "B", ...]`).
  7. `"table"`: Bảng nhỏ dạng `{"columns": ["col1", "col2"], "rows": [[val1, val2], ...]}`.
  8. `"unanswerable"`: Khi dữ liệu hoàn toàn KHÔNG chứa thông tin cần thiết để trả lời câu hỏi (`"answer": null`).
  9. `"abstain"`: Khi không thể xác định chắc chắn câu trả lời (`"answer": null`).

QUY TẮC XẾP HẠNG (RANKING QUESTIONS):
- Chỉ tính trên các đơn hàng hợp lệ (valid orders theo `rulebook`).
- Sắp xếp theo thứ tự GIẢM DẦN (descending) của tiêu chí được hỏi (hoặc tiêu chí mặc định trong `rulebook`).
- Nếu các phần tử có giá trị bằng nhau, sắp xếp theo mã (`code`) TĂNG DẦN (ascending).
- Nếu có ít hơn k ứng viên thỏa mãn, trả về tất cả các ứng viên đó.

LƯU Ý AN TOÀN FILE HỆ THỐNG:
- Thư mục `BUSINESS_DIR` ở chế độ CHỈ ĐỌC (read-only). Tuyệt đối KHÔNG ghi file vào `BUSINESS_DIR`. Nếu cần ghi file tạm, hãy dùng `/tmp`.
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
        f"- **Ngày mốc (`as_of_date`):** `{as_of_date}`",
        "- **Các khoảng thời gian tương đối đã quy đổi sẵn:**",
        date_lines,
    ]
    if calendar_path:
        parts.append(f"- **Đường dẫn file lịch Âm-Dương (`CALENDAR_PATH`):** `{calendar_path}`")

    if rulebook_text:
        parts.extend(
            [
                "",
                "## 2. BỘ QUY TẮC CHUNG (`rulebook`)",
                rulebook_text.strip(),
            ]
        )

    parts.extend(
        [
            "",
            "## 3. CẤU TRÚC DỮ LIỆU CỦA DOANH NGHIỆP",
            schema_markdown,
            "",
            "## 4. YÊU CẦU",
            "Hãy viết một script Python hoàn chỉnh trong khối ```python ... ``` để truy vấn dữ liệu từ `BUSINESS_DIR` và in ra kết quả cuối cùng dưới dạng JSON: `print(json.dumps({\"type\": ..., \"answer\": ...}, ensure_ascii=False))`.",
        ]
    )
    return "\n".join(parts)


def build_error_correction_prompt(previous_code: str, error_message: str) -> str:
    """Prompt sent back to the LLM when the generated Python code fails in the sandbox."""
    return (
        "Đoạn code Python bạn vừa viết gặp lỗi khi thực thi:\n\n"
        f"```text\n{error_message}\n```\n\n"
        "Hãy kiểm tra lại tên file, tên cột, kiểu dữ liệu (xử lý `NaN`, chuỗi ngày tháng, số tiền) "
        "và viết lại đoạn code Python đã sửa lỗi hoàn chỉnh trong khối ```python ... ```."
    )
