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
        "tuần này (this week, Mon-Sun)": f"{this_week_start.isoformat()} .. {this_week_end.isoformat()}",
        "tuần này tính đến hôm nay (week-to-date)": f"{this_week_start.isoformat()} .. {today.isoformat()}",
        "tuần rồi / tuần trước (last week, Mon-Sun)": f"{last_week_start.isoformat()} .. {last_week_end.isoformat()}",
        "tháng này (this month, YYYY-MM)": f"{today.year:04d}-{today.month:02d} ({this_month_start.isoformat()} .. {this_month_end.isoformat()})",
        "tháng này tính đến hôm nay (month-to-date)": f"{this_month_start.isoformat()} .. {today.isoformat()}",
        "tháng rồi / tháng trước (last month, YYYY-MM)": f"{last_month_year:04d}-{last_month:02d} ({last_month_start.isoformat()} .. {last_month_end.isoformat()})",
        "quý này (this quarter)": f"Q{current_quarter}/{today.year} ({this_quarter_start.isoformat()} .. {this_quarter_end.isoformat()})",
        "quý trước (last quarter)": f"Q{last_q}/{last_q_year} ({last_quarter_start.isoformat()} .. {last_quarter_end.isoformat()})",
        "năm nay (this year)": f"{today.year} ({this_year_start.isoformat()} .. {this_year_end.isoformat()})",
        "năm ngoái / năm trước (last year)": f"{today.year - 1} ({last_year_start.isoformat()} .. {last_year_end.isoformat()})",
    }


def load_shared_context(data_dir: str | Path) -> Dict[str, str]:
    """Load shared rulebook and solar-lunar calendar info from the split directory."""
    d_path = Path(data_dir)
    rulebook_text = ""
    calendar_path = ""

    for candidate in ("rulebook.md", "rulebook.txt", "RULES.md"):
        p = d_path / candidate
        if p.exists():
            rulebook_text = p.read_text(encoding="utf-8", errors="replace")
            break

    for cal_candidate in ("calendar.csv", "solar_lunar_calendar.csv", "calendar.json"):
        p = d_path / cal_candidate
        if p.exists():
            calendar_path = str(p.resolve())
            break

    return {
        "rulebook_text": rulebook_text,
        "calendar_path": calendar_path,
    }
