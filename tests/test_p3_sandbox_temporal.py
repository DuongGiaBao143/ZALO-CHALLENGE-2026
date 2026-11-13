"""Independent automated tests for P3: Sandbox Excel unmerge & relative temporal resolution.

Covers:
- Vectorized unmerge_and_ffill (explicit columns and auto-detect)
- Preservation against cross-order leakage (Rulebook Section 8)
- unmerge_openpyxl_sheet utility
- load_excel_unmerge with real data from biz_122 in read-only mode
- "cùng kỳ tháng trước" date interval resolution and leap-year clamping
- Prompt injection for "cùng kỳ tháng trước" and suppression of full-month interval
- Sandbox runtime execution verifying helper availability in global namespace
"""

import os
import openpyxl
import pandas as pd
import pytest

from src.agent.prompts import build_user_prompt
from src.agent.sandbox import (
    load_excel_unmerge,
    run_python_in_sandbox,
    unmerge_and_ffill,
    unmerge_openpyxl_sheet,
)
from src.time_resolver.calendar_utils import resolve_relative_dates


def test_unmerge_and_ffill_explicit():
    """Verify forward-fill on explicitly requested columns."""
    df = pd.DataFrame({
        "order_id": ["DH1", None, "DH2", None],
        "customer": ["An", None, "Binh", None],
        "item": ["Item1", "Item2", "Item3", "Item4"],
        "qty": [1, 2, 3, 4],
    })
    result = unmerge_and_ffill(df, ffill_cols=["order_id", "customer"])
    assert result["order_id"].tolist() == ["DH1", "DH1", "DH2", "DH2"]
    assert result["customer"].tolist() == ["An", "An", "Binh", "Binh"]
    # Item and qty must remain unchanged
    assert result["item"].tolist() == ["Item1", "Item2", "Item3", "Item4"]


def test_unmerge_and_ffill_auto_detect():
    """Verify auto-detection of parent order columns (ma don, ngay, trang thai, ten khach)."""
    df = pd.DataFrame({
        "Mã đơn hàng": ["DH01", None, "DH02", None, None],
        "Ngày đặt hàng": ["2026-05-01", None, "2026-05-02", None, None],
        "Trạng thái": ["Hoàn thành", None, "Đang giao", None, None],
        "Tên sản phẩm": ["Bánh mì", "Sữa tươi", "Cà phê", "Trà sữa", "Bánh ngọt"],
        "Số lượng": [1, 2, 1, 3, 2],
    })
    result = unmerge_and_ffill(df)
    assert result["Mã đơn hàng"].isna().sum() == 0
    assert result["Mã đơn hàng"].tolist() == ["DH01", "DH01", "DH02", "DH02", "DH02"]
    assert result["Ngày đặt hàng"].tolist() == ["2026-05-01", "2026-05-01", "2026-05-02", "2026-05-02", "2026-05-02"]
    assert result["Trạng thái"].tolist() == ["Hoàn thành", "Hoàn thành", "Đang giao", "Đang giao", "Đang giao"]
    assert result["Tên sản phẩm"].tolist() == ["Bánh mì", "Sữa tươi", "Cà phê", "Trà sữa", "Bánh ngọt"]


def test_unmerge_and_ffill_no_cross_order_leakage():
    """Verify Rulebook §8: Walk-in customers (Khách lẻ = None) in Order 2 do NOT inherit Order 1's customer."""
    df = pd.DataFrame({
        "Mã đơn": ["DH01", None, "DH02", None],
        "Tên khách hàng": ["Nguyễn Văn A", None, None, None],
        "Sản phẩm": ["Mì", "Phở", "Cơm", "Cháo"],
    })
    result = unmerge_and_ffill(df)
    # Order 1 child inherits Nguyễn Văn A
    assert result.loc[1, "Tên khách hàng"] == "Nguyễn Văn A"
    # Order 2 is a separate order with no customer, so row 2 and 3 must remain null (no leakage from Order 1!)
    assert pd.isna(result.loc[2, "Tên khách hàng"])
    assert pd.isna(result.loc[3, "Tên khách hàng"])


def test_unmerge_openpyxl_sheet():
    """Verify openpyxl sheet unmerging replicates top-left cell values across merged cells."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "ORDER_001"
    ws.merge_cells("A1:A3")
    ws["B1"] = "Item 1"
    ws["B2"] = "Item 2"
    ws["B3"] = "Item 3"

    assert len(ws.merged_cells.ranges) == 1
    unmerge_openpyxl_sheet(ws)
    assert len(ws.merged_cells.ranges) == 0

    assert ws["A1"].value == "ORDER_001"
    assert ws["A2"].value == "ORDER_001"
    assert ws["A3"].value == "ORDER_001"


def test_load_excel_unmerge_real_data():
    """Verify load_excel_unmerge on real training data biz_122 (sheet T09-2025)."""
    file_path = "data/train/data/biz_122/DonHang_ChiTiet_1.xlsx"
    if os.path.exists(file_path):
        df = load_excel_unmerge(file_path, sheet_name="T09-2025", header=2)
        assert len(df) == 5635
        # Originally 2654 nulls in Mã đơn hàng; with unmerge, must be 0 nulls!
        assert df["Mã đơn hàng"].isna().sum() == 0
        assert df["Ngày đặt hàng"].isna().sum() == 0
        assert df["Trạng thái đơn hàng"].isna().sum() == 0


def test_resolve_relative_dates_cung_ky():
    """Verify 'cùng kỳ tháng trước' interval for as_of_date 2025-08-03."""
    rel = resolve_relative_dates("2025-08-03")
    assert "cùng kỳ tháng trước / so với tháng trước (theo Rulebook: cùng số ngày từ ngày 1 đến ngày trùng hôm nay ở tháng trước)" in rel
    interval = rel["cùng kỳ tháng trước / so với tháng trước (theo Rulebook: cùng số ngày từ ngày 1 đến ngày trùng hôm nay ở tháng trước)"]
    assert interval == "2025-07-01 .. 2025-07-03"


def test_resolve_relative_dates_leap_year_clamp():
    """Verify clamp to last day of February when as_of_date is March 31."""
    # 2025 is non-leap year (Feb has 28 days)
    rel_2025 = resolve_relative_dates("2025-03-31")
    interval_2025 = rel_2025["cùng kỳ tháng trước / so với tháng trước (theo Rulebook: cùng số ngày từ ngày 1 đến ngày trùng hôm nay ở tháng trước)"]
    assert interval_2025 == "2025-02-01 .. 2025-02-28"

    # 2024 is leap year (Feb has 29 days)
    rel_2024 = resolve_relative_dates("2024-03-31")
    interval_2024 = rel_2024["cùng kỳ tháng trước / so với tháng trước (theo Rulebook: cùng số ngày từ ngày 1 đến ngày trùng hôm nay ở tháng trước)"]
    assert interval_2024 == "2024-02-01 .. 2024-02-29"


def test_build_user_prompt_temporal_injection():
    """Verify prompt injects 'cùng kỳ tháng trước' and suppresses full month 'tháng rồi / tháng trước'."""
    question = "So với cùng kỳ tháng trước, doanh thu từ đầu tháng này đến hết hôm nay tăng hay giảm bao nhiêu %?"
    as_of_date = "2025-08-03"
    rel_dates = resolve_relative_dates(as_of_date)

    prompt = build_user_prompt(
        question=question,
        as_of_date=as_of_date,
        relative_dates=rel_dates,
        schema_markdown="Schema...",
        core_rules=True,
    )

    # Must contain same-period interval: 2025-07-01 .. 2025-07-03
    assert "2025-07-01 .. 2025-07-03" in prompt
    # Must contain current month interval: 2025-08-01 .. 2025-08-03
    assert "2025-08-01 .. 2025-08-03" in prompt
    # Must NOT contain the full previous month: 2025-07-01 .. 2025-07-31
    assert "2025-07-01 .. 2025-07-31" not in prompt


def test_sandbox_globals(tmp_path):
    """Verify that unmerge_and_ffill and load_excel_unmerge are available in sandbox code without importing."""
    code = (
        "import json, pandas as pd\n"
        "df = pd.DataFrame({'Mã đơn': ['D1', None], 'Giá trị': [100, 200]})\n"
        "res = unmerge_and_ffill(df)\n"
        "assert res['Mã đơn'].tolist() == ['D1', 'D1']\n"
        "assert callable(load_excel_unmerge)\n"
        "assert callable(unmerge_openpyxl_sheet)\n"
        "print(json.dumps({'kind': 'final', 'type': 'boolean', 'answer': True, 'evidence': 'unmerge works'}))\n"
    )
    sb_res = run_python_in_sandbox(
        code=code,
        business_dir=str(tmp_path),
        work_dir=str(tmp_path),
        as_of_date="2026-08-01",
    )
    assert sb_res.success is True
    assert sb_res.parsed_output["kind"] == "final"
    assert sb_res.parsed_output["answer"] is True


def test_unmerge_and_ffill_unmerged_table_no_leakage():
    """Verify that a standard unmerged table with complete order IDs does NOT leak customer names to walk-ins."""
    df = pd.DataFrame({
        "Mã đơn": ["DH01", "DH02"],
        "Tên khách hàng": ["Nguyễn Văn A", None],
        "Sản phẩm": ["Mì", "Phở"]
    })
    res = unmerge_and_ffill(df)
    assert res.loc[0, "Tên khách hàng"] == "Nguyễn Văn A"
    assert pd.isna(res.loc[1, "Tên khách hàng"])

    # Multi-order test case matching reviewer reproduction
    df_multi = pd.DataFrame({
        "Mã đơn": ["DH1", "DH2", "DH3"],
        "Tên khách": ["Nguyễn Văn A", None, None],
    })
    res_multi = unmerge_and_ffill(df_multi)
    assert res_multi.loc[0, "Tên khách"] == "Nguyễn Văn A"
    assert pd.isna(res_multi.loc[1, "Tên khách"])
    assert pd.isna(res_multi.loc[2, "Tên khách"])


def test_load_excel_unmerge_default_header(tmp_path):
    """Verify load_excel_unmerge defaults to header=0 like pd.read_excel, preserving string column names."""
    test_file = tmp_path / "test_orders.xlsx"
    df_orig = pd.DataFrame({
        "Mã đơn": ["DH01", "DH02"],
        "Tên khách": ["Khách A", None],
        "Tiền": [100000, 200000],
    })
    df_orig.to_excel(test_file, index=False)

    df_loaded = load_excel_unmerge(test_file)
    assert list(df_loaded.columns) == ["Mã đơn", "Tên khách", "Tiền"]
    assert df_loaded["Mã đơn"].iloc[0] == "DH01"
    assert pd.isna(df_loaded["Tên khách"].iloc[1])

