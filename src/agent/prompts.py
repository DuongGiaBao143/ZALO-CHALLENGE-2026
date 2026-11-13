"""Prompt templates for the DataMate single-model baseline (Qwen2.5-Coder-7B-Instruct)."""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from typing import Any, Dict

BASE_SYSTEM_PROMPT = """Trả đúng một khối ```python chứa script hoàn chỉnh. Script phải chạy ngay và in kết quả; nếu định nghĩa main(), hãy gọi main(). Mỗi lượt chạy độc lập.
Các biến đường dẫn được môi trường thực thi cấp: BUSINESS_DIR (chỉ đọc), RULEBOOK_PATH, CALENDAR_PATH. AS_OF_DATE là chuỗi YYYY-MM-DD. Có sẵn pd, np, json, sqlite3. Gọi trực tiếp parse_vn_number(series), parse_vn_date(series, default_year=...) và vn_norm(x); không import chúng như module hay tự định nghĩa lại. Có sẵn load_excel_unmerge(path, sheet_name=...) và unmerge_and_ffill(df) để xử lý bảng Excel gộp ô hoặc dòng con để trống thông tin đơn/ngày/trạng thái (theo Rulebook §8).
Dùng dữ liệu thật và luật liên quan. Không ghi vào nguồn, đoán schema hay suy đáp án từ ID. Kiểm tra header nếu chưa rõ và đọc đủ các file liên quan. Chọn cột ngày đúng nghiệp vụ và chuẩn hóa cùng kiểu trước khi lọc. Trước khi nối, kiểm tra khóa duy nhất ở phía một để tránh nhân dòng; xử lý trùng theo rulebook. Khi cần đơn vị cơ bản, dùng cột đã quy đổi nếu đúng định nghĩa.
Đủ dữ kiện thì tính và in final. Chỉ dùng observation để làm rõ một điểm cụ thể khi còn lượt sau. Khi runner báo lỗi kỹ thuật, sửa theo lỗi đã báo trước khi cân nhắc abstain. Chỉ abstain khi không thể tính đáng tin; unanswerable khi đã xác minh dữ liệu không đủ.
Dòng stdout cuối là một JSON object (không NaN/Infinity):
- Khám phá: {"kind":"observation","data":...,"message":"..."}; chỉ in phần cần kiểm tra.
- Kết quả: {"kind":"final","type":"...","answer":...,"evidence":"file/cột và phép tính đã dùng"}. Chọn đúng một type: number, percent, string, date, boolean, list, table, unanswerable, abstain.
Tiền VND là số nguyên; percent là số phần trăm (12.4 cho 12.4%); date là YYYY-MM-DD hoặc YYYY-MM. List giữ thứ tự; table có columns và rows. Top k giảm dần theo tiêu chí; bằng nhau thì mã tăng dần, thiếu mã dùng tên. abstain và unanswerable có answer=null; unanswerable cần reason nêu dữ liệu thiếu. Runner tạo submission.
"""

SYSTEM_PROMPT = BASE_SYSTEM_PROMPT


def build_system_prompt(rulebook_text: str = "") -> str:
    """Build complete system prompt containing execution protocols and the full business rulebook."""
    if not rulebook_text or not rulebook_text.strip():
        return BASE_SYSTEM_PROMPT
    return (
        f"{BASE_SYSTEM_PROMPT}\n\n"
        "# QUY TẮC NGHIỆP VỤ BẮT BUỘC (RULEBOOK)\n"
        "Toàn bộ quy định nghiệp vụ chung của hệ thống được nêu dưới đây. "
        "Mọi phép tính doanh thu, công nợ, chiết khấu, lọc đơn huỷ/trả, phân loại khách hàng, "
        "và xử lý đồng hạng PHẢI TUÂN THỦ TUYỆT ĐỐI quy tắc này:\n\n"
        f"{rulebook_text.strip()}"
    )

CORE_CHEATSHEET = """Quy tắc nghiệp vụ cốt lõi
- Doanh thu và lượng bán theo ngày đặt. Bỏ cả đơn huỷ/trả, kể cả trả một phần; đơn đang giao vẫn tính. Dùng nhãn thật, tránh regex chứa "hoàn" đơn lẻ.
- Doanh thu = thành tiền các dòng sau giảm giá dòng, chưa trừ voucher cả đơn, không VAT/phí giao. Trung bình đơn = doanh thu / số mã đơn hợp lệ phân biệt; làm tròn về đồng, nửa đồng làm tròn lên.
- Nhóm khách theo mã; shop chỉ có tên thì gộp cách viết cùng tên. Bỏ khách lẻ khi đếm/xếp hạng khách.
- Đổi về đơn vị cơ bản theo hệ số từng mặt hàng khi chỉ số yêu cầu.
- Công nợ theo luật riêng; đơn trả vẫn tính nếu còn nợ. Nợ/tồn đến ngày X tính tích lũy đến hết X.
- Đồng hạng: mã tăng dần, thiếu mã dùng tên. Phân biệt số 0 với kỳ ngoài phạm vi dữ liệu.
- Ưu tiên yêu cầu câu hỏi. Đọc luật chuyên biệt tại RULEBOOK_PATH của split đang chạy."""


def _search_text(text: str) -> str:
    """Normalize a copy for matching; preserve accents in excerpts and output."""
    folded = unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
    return " " + " ".join(re.findall(r"[a-z0-9]+", folded.encode("ascii", "ignore").decode())) + " "


def _mentions(query: str, phrases: str) -> bool:
    return any(_search_text(phrase) in query for phrase in phrases.split("|"))


@lru_cache(maxsize=4)
def _rule_sections(text: str) -> dict[int, str]:
    matches = list(re.finditer(r"^##\s+(\d+)\.\s+[^\n]+$", text, re.MULTILINE))
    return {
        int(match[1]): text[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()
        for i, match in enumerate(matches)
    }


def _select_rules(rulebook: str, query: str) -> str:
    sections = _rule_sections(rulebook)
    # shortcut: phrase routing handles common metrics; read RULEBOOK_PATH for uncovered wording.
    quantity_rank = _mentions(query, "bán chạy|bán nhiều nhất|bán được nhiều nhất|hot nhất")
    sales = _mentions(query, "doanh thu|dthu|tiền bán|tiền hàng|số đơn|đơn huỷ|tiền mặt|thu về|tỉ lệ hủy")
    debt = _mentions(query, "công nợ|còn nợ|mua chịu|bán chịu|trả nợ|thu nợ|tuổi nợ|nợ thêm|khách nợ|trả bớt nợ")
    stock = _mentions(query, "tồn kho|còn tồn|còn hàng|hết hàng|nhập hàng|nhà cung cấp|giá vốn|lãi gộp|lãi ròng|hàng lời|giá bán|tăng giá")
    ranking = _mentions(query, "top|xếp hạng|sộp nhất|trung thành nhất|đổi ý nhất|ưa chuộng nhất|chăm chỉ nhất|đắt khách nhất|bán giỏi nhất|giờ cao điểm")

    # Only select dependencies of the identified metric. Debt has its own status rules.
    selected = {8}
    rows_by_section = {}
    if sales:
        selected.add(1)
    if debt:
        selected.add(4)
        rows_by_section[3] = {"xác định khách"}
    if stock:
        selected.update((5, 10))
    if quantity_rank:
        selected.add(10)
        rows_by_section[1] = {"đơn tính vào doanh thu", "đơn thuộc kỳ nào"}
        rows_by_section.setdefault(3, set()).update(("mặt hàng", "bán chạy"))
    elif ranking and not (debt or stock):
        selected.update((1, 3))

    excerpts = ["\n".join(line for line in sections.get(7, "").splitlines() if line.startswith("- "))]
    for number in sorted(selected | rows_by_section.keys()):
        section = sections.get(number, "")
        if not section:
            continue
        if number in selected:
            excerpts.append(section)
        else:
            labels = {_search_text(label) for label in rows_by_section[number]}
            rows = [line for line in section.splitlines() if line.startswith("|")
                    and _search_text(line.split("|")[1]) in labels]
            if rows:
                excerpts.append(section.splitlines()[0] + "\n" + "\n".join(rows))
    return "\n\n".join(filter(None, excerpts))


def build_user_prompt(
    question: str,
    as_of_date: str,
    relative_dates: Dict[str, str],
    schema_markdown: str,
    rulebook_text: str = "",
    calendar_path: str = "",
    *,
    core_rules: bool = False,
    readme_text: str = "",
    rulebook_in_system: bool = False,
) -> str:
    """Render question, profiled schema, and source rule excerpts without model calls."""
    query = _search_text(question)
    parts = [f"Câu hỏi: {question}\nas_of_date: {as_of_date}"]
    same_period = (
        _mentions(query, "cung ky thang truoc|cung ky thang roi|so voi cung ky|cung ky")
        or (_mentions(query, "so voi thang truoc|so voi thang roi") and not _mentions(query, "ca thang truoc"))
        or (_mentions(query, "thang nay") and _mentions(query, "so voi thang truoc|so voi thang roi|cung ky"))
    )
    dates = []
    for label, value in relative_dates.items():
        if label.startswith("as_of_date"):
            continue
        # If comparing same period, suppress the full prior month interval to prevent model confusion
        if same_period and label.startswith("tháng rồi / tháng trước"):
            continue
        phrases = label.split(" (", 1)[0].replace(" / ", "|")
        is_same_period_label = label.startswith("cùng kỳ tháng trước") or label.startswith("so với tháng trước")
        if is_same_period_label:
            matches = same_period
        elif same_period and label.startswith("tháng này"):
            matches = True
        else:
            matches = _mentions(query, phrases)
        if matches:
            dates.append(f"- {label}: {value}")
    if rulebook_in_system and dates:
        cleaned_dates = []
        for entry in dates:
            if entry.startswith("- quy ước ca làm việc"):
                continue
            cleaned_dates.append(re.sub(r"\s*\([^)]*rulebook[^)]*\)", "", entry, flags=re.IGNORECASE))
        dates = cleaned_dates
    if dates:
        heading = "Mốc thời gian:" if rulebook_in_system else "Mốc thời gian (hai đầu đều tính):"
        parts.append(heading + "\n" + "\n".join(dates))
    lunar = calendar_path and _mentions(query, "tết|lịch âm|âm lịch|tháng chạp|tháng giêng")
    if core_rules and lunar:
        parts.append("Lịch âm-dương: CALENDAR_PATH.")
    parts.append(schema_markdown)
    if core_rules:
        parts.append(CORE_CHEATSHEET)
        if readme_text.strip():
            parts.append("README của shop:\n" + readme_text.strip())
        parts.append(
            f"Nhắc lại nhiệm vụ: Viết Python giải câu hỏi “{question}”. Đủ căn cứ thì in JSON kind='final'. "
            "Với xếp hạng rỗng, kèm check gồm source_file, table, detail và rows_after_filter đo từ dữ liệu đã lọc. "
            "Chỉ dùng observation để xác minh một điểm cụ thể khi còn lượt."
        )
        return "\n\n".join(parts)
    if rulebook_text and not rulebook_in_system:
        rules = _select_rules(rulebook_text, query)
        if rules:
            parts.append("Trích rulebook:\n" + rules)
        parts.append(
            "Luật đầy đủ tại RULEBOOK_PATH, gồm luật riêng theo ngành. "
            "Áp dụng yêu cầu cụ thể trong câu hỏi; nếu trích đoạn thiếu luật cần dùng, đọc mục tương ứng."
        )
    if lunar:
        parts.append("Lịch âm-dương: CALENDAR_PATH.")
    parts.append(
        f"--- BẮT BUỘC: Viết một script Python hoàn chỉnh trong khối ```python ... ``` để giải câu hỏi: “{question}”. "
        "Script phải chạy ngay trên dữ liệu thật và in một JSON protocol duy nhất ở dòng stdout cuối cùng."
    )
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
        "Viết lại một script Python hoàn chỉnh dựa trên quan sát này. Đọc lại các file cần dùng vì lượt chạy mới "
        "không có biến của lượt trước. Nếu đã đủ dữ kiện, tính và in JSON kind='final'."
    )


def build_error_correction_prompt(
    error_message: str,
    error_kind: str = "runtime_error",
    question: str = "",
    as_of_date: str = "",
) -> str:
    """Prompt sent back to model when code execution or protocol validation fails."""
    hint = ""
    if "No module named" in error_message and any(
        helper in error_message for helper in ("parse_vn_number", "parse_vn_date", "vn_norm")
    ):
        hint = "Bỏ lệnh import helper bị lỗi. Các hàm này đã có sẵn; gọi trực tiếp.\n"
    elif "no output on stdout" in error_message:
        hint = "Gọi hàm thực hiện phép tính và dùng print(json.dumps(...)) để in JSON kết quả.\n"
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
        f"{hint}"
        "Dựa vào lỗi và schema, viết lại script Python hoàn chỉnh. Nếu cần khám phá thêm, xuất observation; "
        "không chỉ đổi định dạng để che lỗi tính toán."
    )
