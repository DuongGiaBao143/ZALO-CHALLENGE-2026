"""Prompt templates for the DataMate single-model baseline (Qwen2.5-Coder-7B-Instruct)."""

from __future__ import annotations

import json
from typing import Any, Dict

SYSTEM_PROMPT = """Viết script Python hoàn chỉnh trong khối ```python ... ``` để trả lời từ dữ liệu thật. BUSINESS_DIR chỉ đọc; có AS_OF_DATE, RULEBOOK_PATH, CALENDAR_PATH, pandas, numpy, json, sqlite3 và parse_vn_number, parse_vn_date, vn_norm. Các biến đường dẫn được môi trường thực thi cấp; dùng trực tiếp, không gán đường dẫn tuyệt đối. Dùng ngày mốc, README và quy tắc liên quan; không đoán cột hay dữ kiện thiếu. Mỗi lượt chạy độc lập.
Dòng stdout cuối là JSON một dòng:
- Khám phá/đọc quy tắc: {"kind":"observation","data":...,"message":"..."} (tối đa 3200 ký tự data).
- Kết luận: {"kind":"final","type":"number|percent|string|date|boolean|list|table|unanswerable|abstain","answer":...,"evidence":"nguồn và phép tính"}.
Table: {"columns":[...],"rows":[[...]]}. Thiếu căn cứ: unanswerable kèm reason; chưa giải được: abstain. Không xuất NaN/Infinity. Không đổi dữ liệu hay suy đáp án từ ID. Đọc RULEBOOK_PATH khi cần quy tắc chưa có trong README; xuất observation để xem nội dung trước khi tính.
"""


def build_user_prompt(
    question: str,
    as_of_date: str,
    relative_dates: Dict[str, str],
    schema_markdown: str,
    rulebook_text: str = "",
    calendar_path: str = "",
) -> str:
    """Use README/schema and task metadata; business rules remain available to the runner."""
    parts = [schema_markdown]
    if rulebook_text:
        parts.append("Quy tắc nghiệp vụ: RULEBOOK_PATH (đọc mục liên quan khi cần).")
    if calendar_path:
        parts.append("Lịch âm-dương: CALENDAR_PATH.")
    parts.extend([f"as_of_date: {as_of_date}", f"Câu hỏi: {question}"])
    return "\n\n".join(parts)


def build_observation_prompt(
    observation_data: Any,
    message: str = "",
    question: str = "",
    as_of_date: str = "",
) -> str:
    """Prompt sent back to model after a successful observation step."""
    obs_repr = json.dumps(observation_data, ensure_ascii=False, indent=2)
    note = f" ({message})" if message else ""
    anchor = ""
    if question:
        anchor = (
            f"\n**Nhắc lại câu hỏi cần trả lời:** {question}\n"
            f"**Ngày mốc (`as_of_date` / Hôm nay):** `{as_of_date}`\n"

        )
    return (
        f"Dữ liệu quan sát thu được từ code vừa chạy{note}:\n\n"
        f"```json\n{obs_repr}\n```\n"
        f"{anchor}"
        "Dựa vào thông tin này, hãy viết tiếp đoạn code Python trong khối ```python ... ``` để thực hiện "
        "bước tiếp theo hoặc tính toán kết quả cuối cùng và in ra JSON theo protocol `kind='final'`."
    )


def build_error_correction_prompt(
    error_message: str,
    error_kind: str = "runtime_error",
    question: str = "",
    as_of_date: str = "",
) -> str:
    """Prompt sent back to model when code execution or protocol validation fails."""
    anchor = ""
    if question:
        anchor = (
            f"\n**Nhắc lại câu hỏi cần trả lời:** {question}\n"
            f"**Ngày mốc (`as_of_date` / Hôm nay):** `{as_of_date}`\n"
        )
    return (
        f"Đoạn code Python bạn vừa viết gặp sự cố ({error_kind}):\n\n"
        f"```text\n{error_message}\n```\n"
        f"{anchor}\n"
        "Dựa vào lỗi và schema, viết lại script Python hoàn chỉnh. Nếu cần khám phá thêm, xuất observation; "
        "không chỉ đổi định dạng để che lỗi tính toán."
    )
