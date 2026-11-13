"""Deterministic resolver for `as_of_date` relative intervals and shared rulebook."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict


def _last_day_of_month(year: int, month: int) -> date:
    _, last_day = calendar.monthrange(year, month)
    return date(year, month, last_day)


def resolve_relative_dates(as_of_date_str: str) -> Dict[str, str]:
    """Compute common Vietnamese relative date intervals anchored at `as_of_date`.

    Pre-calculating these in Python prevents the LLM from making calendar arithmetic errors.
    Strictly follows DataMate Rulebook Section 2:
      - 'tuần này': từ thứ Hai của tuần chứa hôm nay đến HẾT HÔM NAY (as_of_date).
      - 'tuần trước / tuần rồi': CẢ tuần liền trước, thứ Hai đến Chủ nhật.
      - 'tháng này': từ ngày 1 đến HẾT HÔM NAY (as_of_date).
      - 'so với tháng trước': cùng số ngày của tháng trước (từ ngày 1 đến ngày trùng số với hôm nay;
        nếu tháng trước không có ngày đó thì đến hết tháng trước).
      - 'tháng M/Y': cả tháng, từ ngày 1 đến hết ngày cuối tháng.
      - 'từ đầu năm / từ đầu năm tới nay': từ 01/01 của năm nay đến HẾT HÔM NAY.
    """
    today = datetime.strptime(as_of_date_str.strip(), "%Y-%m-%d").date()
    yesterday = today - timedelta(days=1)

    # ISO week: Monday (0) to Sunday (6)
    this_week_start = today - timedelta(days=today.weekday())
    this_week_end = this_week_start + timedelta(days=6)
    last_week_start = this_week_start - timedelta(days=7)
    last_week_end = this_week_start - timedelta(days=1)

    # Month boundaries
    this_month_start = date(today.year, today.month, 1)
    this_month_end = _last_day_of_month(today.year, today.month)

    if today.month == 1:
        last_month_year, last_month = today.year - 1, 12
    else:
        last_month_year, last_month = today.year, today.month - 1
    last_month_start = date(last_month_year, last_month, 1)
    last_month_end = _last_day_of_month(last_month_year, last_month)
    last_month_same_period_end = date(
        last_month_year, last_month, min(today.day, last_month_end.day)
    )

    # Quarter boundaries
    current_quarter = (today.month - 1) // 3 + 1
    this_q_start_month = (current_quarter - 1) * 3 + 1
    this_quarter_start = date(today.year, this_q_start_month, 1)
    this_quarter_end = _last_day_of_month(today.year, this_q_start_month + 2)

    if current_quarter == 1:
        last_q_year, last_q = today.year - 1, 4
    else:
        last_q_year, last_q = today.year, current_quarter - 1
    last_q_start_month = (last_q - 1) * 3 + 1
    last_quarter_start = date(last_q_year, last_q_start_month, 1)
    last_quarter_end = _last_day_of_month(last_q_year, last_q_start_month + 2)

    # Year boundaries
    this_year_start = date(today.year, 1, 1)
    this_year_end = date(today.year, 12, 31)
    last_year_start = date(today.year - 1, 1, 1)
    last_year_end = date(today.year - 1, 12, 31)

    return {
        "as_of_date (hôm nay / today)": today.isoformat(),
        "hôm qua (yesterday)": yesterday.isoformat(),
        "tuần này (theo Rulebook: từ thứ Hai đến hết hôm nay)": f"{this_week_start.isoformat()} .. {today.isoformat()}",
        "tuần rồi / tuần trước (theo Rulebook: cả tuần liền trước, thứ Hai đến Chủ nhật)": f"{last_week_start.isoformat()} .. {last_week_end.isoformat()}",
        "cả tuần hiện tại (thứ Hai đến Chủ nhật, chỉ dùng nếu câu hỏi hỏi cả tuần lịch)": f"{this_week_start.isoformat()} .. {this_week_end.isoformat()}",
        "tháng này (theo Rulebook: từ ngày 1 đến hết hôm nay)": f"{this_month_start.isoformat()} .. {today.isoformat()}",
        "cùng kỳ tháng trước / so với tháng trước (theo Rulebook: cùng số ngày từ ngày 1 đến ngày trùng hôm nay ở tháng trước)": f"{last_month_start.isoformat()} .. {last_month_same_period_end.isoformat()}",
        "so với tháng trước (cùng số ngày từ ngày 1 đến ngày trùng hôm nay ở tháng trước)": f"{last_month_start.isoformat()} .. {last_month_same_period_end.isoformat()}",
        "tháng rồi / tháng trước (theo Rulebook: cả tháng liền trước, từ ngày 1 đến hết tháng)": f"{last_month_start.isoformat()} .. {last_month_end.isoformat()}",
        "cả tháng lịch hiện tại (từ ngày 1 đến hết tháng, chỉ dùng nếu câu hỏi hỏi đích danh Tháng M/YYYY)": f"{this_month_start.isoformat()} .. {this_month_end.isoformat()}",
        "từ đầu năm tới nay (theo Rulebook: từ 01/01 đến hết hôm nay)": f"{this_year_start.isoformat()} .. {today.isoformat()}",
        "quý này (từ đầu quý đến hết hôm nay)": f"{this_quarter_start.isoformat()} .. {today.isoformat()}",
        "cả quý này (nếu câu hỏi hỏi đích danh Quý Q/YYYY)": f"{this_quarter_start.isoformat()} .. {this_quarter_end.isoformat()}",
        "quý trước (cả quý liền trước)": f"Q{last_q}/{last_q_year} ({last_quarter_start.isoformat()} .. {last_quarter_end.isoformat()})",
        "năm nay (cả năm lịch YYYY)": f"{today.year} ({this_year_start.isoformat()} .. {this_year_end.isoformat()})",
        "năm ngoái / năm trước (cả năm lịch YYYY-1)": f"{today.year - 1} ({last_year_start.isoformat()} .. {last_year_end.isoformat()})",
        "dịp Tết 2026 (23 tháng Chạp đến mùng 10 tháng Giêng theo Rulebook)": "2026-02-10 .. 2026-02-26",
        "17 ngày ngay trước Tết 2026 (theo Rulebook)": "2026-01-24 .. 2026-02-09",
        "dịp Tết 2025 (23 tháng Chạp đến mùng 10 tháng Giêng theo Rulebook)": "2025-01-22 .. 2025-02-07",
        "17 ngày ngay trước Tết 2025 (theo Rulebook)": "2025-01-05 .. 2025-01-21",
        "quy ước ca làm việc (theo Rulebook)": "Ca sáng: 06:00 - 13:59 | Ca chiều: 14:00 - 21:59",
    }


def load_shared_context(data_dir: str | Path) -> Dict[str, str]:
    """Load shared rulebook and solar-lunar calendar info from the split directory."""
    d_path = Path(data_dir)
    rulebook_text = ""
    rulebook_path = ""
    calendar_path = ""

    for candidate in ("rulebook.md", "rulebook.txt", "RULES.md"):
        p = d_path / candidate
        if p.exists():
            rulebook_text = p.read_text(encoding="utf-8", errors="replace")
            rulebook_path = str(p.resolve())
            break

    for cal_candidate in ("calendar.csv", "solar_lunar_calendar.csv", "calendar.json"):
        p = d_path / cal_candidate
        if p.exists():
            calendar_path = str(p.resolve())
            break

    return {
        "rulebook_text": rulebook_text,
        "rulebook_path": rulebook_path,
        "calendar_path": calendar_path,
    }
