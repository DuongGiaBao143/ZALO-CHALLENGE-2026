"""Unit tests for time_resolver calendar_utils following DataMate Rulebook Section 2."""

from datetime import date
import pytest

from src.time_resolver.calendar_utils import resolve_relative_dates, _last_day_of_month


def test_last_day_of_month():
    # February standard vs leap year
    assert _last_day_of_month(2026, 2) == date(2026, 2, 28)
    assert _last_day_of_month(2024, 2) == date(2024, 2, 29)
    # Months with 30 and 31 days
    assert _last_day_of_month(2026, 9) == date(2026, 9, 30)
    assert _last_day_of_month(2026, 8) == date(2026, 8, 31)


def test_resolve_relative_dates_2026_09_07():
    """Verify example date from DataMate documentation: 2026-09-07 (Monday)."""
    rel = resolve_relative_dates("2026-09-07")

    # Today & Yesterday
    assert rel["as_of_date (hôm nay / today)"] == "2026-09-07"
    assert rel["hôm qua (yesterday)"] == "2026-09-06"

    # Tuần này: from Monday 2026-09-07 to as_of_date (2026-09-07)
    assert rel["tuần này (theo Rulebook: từ thứ Hai đến hết hôm nay)"] == "2026-09-07 .. 2026-09-07"

    # Tuần trước: entire previous week (Monday to Sunday)
    assert rel["tuần rồi / tuần trước (theo Rulebook: cả tuần liền trước, thứ Hai đến Chủ nhật)"] == "2026-08-31 .. 2026-09-06"

    # Cả tuần hiện tại
    assert rel["cả tuần hiện tại (thứ Hai đến Chủ nhật, chỉ dùng nếu câu hỏi hỏi cả tuần lịch)"] == "2026-09-07 .. 2026-09-13"

    # Tháng này: 1st of month to as_of_date
    assert rel["tháng này (theo Rulebook: từ ngày 1 đến hết hôm nay)"] == "2026-09-01 .. 2026-09-07"

    # So với tháng trước: same day count (1 to 7) of previous month
    assert rel["so với tháng trước (cùng số ngày từ ngày 1 đến ngày trùng hôm nay ở tháng trước)"] == "2026-08-01 .. 2026-08-07"

    # Tháng trước / tháng rồi: entire previous month
    assert rel["tháng rồi / tháng trước (theo Rulebook: cả tháng liền trước, từ ngày 1 đến hết tháng)"] == "2026-08-01 .. 2026-08-31"

    # Cả tháng lịch hiện tại
    assert rel["cả tháng lịch hiện tại (từ ngày 1 đến hết tháng, chỉ dùng nếu câu hỏi hỏi đích danh Tháng M/YYYY)"] == "2026-09-01 .. 2026-09-30"

    # Từ đầu năm tới nay
    assert rel["từ đầu năm tới nay (theo Rulebook: từ 01/01 đến hết hôm nay)"] == "2026-01-01 .. 2026-09-07"


def test_resolve_relative_dates_month_boundary_february():
    """Verify month boundary where last month has fewer days (31 March -> 28 February in 2026)."""
    rel = resolve_relative_dates("2026-03-31")

    assert rel["tháng này (theo Rulebook: từ ngày 1 đến hết hôm nay)"] == "2026-03-01 .. 2026-03-31"
    # Rulebook: "tháng trước không có ngày đó thì đến hết tháng trước" -> 2026-02-28
    assert rel["so với tháng trước (cùng số ngày từ ngày 1 đến ngày trùng hôm nay ở tháng trước)"] == "2026-02-01 .. 2026-02-28"
    assert rel["tháng rồi / tháng trước (theo Rulebook: cả tháng liền trước, từ ngày 1 đến hết tháng)"] == "2026-02-01 .. 2026-02-28"


def test_resolve_relative_dates_leap_year_february():
    """Verify leap year boundary (31 March 2024 -> 29 February 2024)."""
    rel = resolve_relative_dates("2024-03-31")

    assert rel["so với tháng trước (cùng số ngày từ ngày 1 đến ngày trùng hôm nay ở tháng trước)"] == "2024-02-01 .. 2024-02-29"
    assert rel["tháng rồi / tháng trước (theo Rulebook: cả tháng liền trước, từ ngày 1 đến hết tháng)"] == "2024-02-01 .. 2024-02-29"


def test_resolve_relative_dates_year_boundary():
    """Verify year boundary in early January (e.g. 2026-01-05)."""
    rel = resolve_relative_dates("2026-01-05")

    # 2026-01-05 is a Monday
    assert rel["tuần này (theo Rulebook: từ thứ Hai đến hết hôm nay)"] == "2026-01-05 .. 2026-01-05"
    assert rel["tuần rồi / tuần trước (theo Rulebook: cả tuần liền trước, thứ Hai đến Chủ nhật)"] == "2025-12-29 .. 2026-01-04"
    assert rel["tháng này (theo Rulebook: từ ngày 1 đến hết hôm nay)"] == "2026-01-01 .. 2026-01-05"
    assert rel["so với tháng trước (cùng số ngày từ ngày 1 đến ngày trùng hôm nay ở tháng trước)"] == "2025-12-01 .. 2025-12-05"
    assert rel["tháng rồi / tháng trước (theo Rulebook: cả tháng liền trước, từ ngày 1 đến hết tháng)"] == "2025-12-01 .. 2025-12-31"
    assert rel["từ đầu năm tới nay (theo Rulebook: từ 01/01 đến hết hôm nay)"] == "2026-01-01 .. 2026-01-05"
    assert rel["năm ngoái / năm trước (cả năm lịch YYYY-1)"] == "2025 (2025-01-01 .. 2025-12-31)"


def test_resolve_relative_dates_week_end():
    """Verify Sunday as as_of_date (2026-09-13)."""
    rel = resolve_relative_dates("2026-09-13")

    # Sunday: full week from Monday to Sunday
    assert rel["tuần này (theo Rulebook: từ thứ Hai đến hết hôm nay)"] == "2026-09-07 .. 2026-09-13"
    assert rel["cả tuần hiện tại (thứ Hai đến Chủ nhật, chỉ dùng nếu câu hỏi hỏi cả tuần lịch)"] == "2026-09-07 .. 2026-09-13"
    assert rel["tháng này (theo Rulebook: từ ngày 1 đến hết hôm nay)"] == "2026-09-01 .. 2026-09-13"
