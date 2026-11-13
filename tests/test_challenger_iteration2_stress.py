"""Empirical Challenger Adversarial Stress Suite for Iteration 2 Refinements.

Covers:
1. Walk-in customers (None / NaN / empty) protection on standard unmerged order sheets.
2. `load_excel_unmerge` default header=0 and custom header options with column name preservation.
3. `_eval_guard_issue` handling of debt tables with formatted strings ('150,000', '150.000', etc.) vs zero-debt tables.
4. `_eval_guard_issue` blocking of string zeros (['0', '0'], ['0.0', '0.0'], ['0,0', '0,00'], [' 0 ', '-0']).
5. Sandbox runtime execution ensuring helper parity and zero cross-order leakage.
"""

from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest

from src.agent.sandbox import (
    load_excel_unmerge,
    run_python_in_sandbox,
    unmerge_and_ffill,
)
from src.agent.solver import _eval_guard_issue
from src.schemas import BusinessProfile


@pytest.fixture
def empty_profile():
    return BusinessProfile(
        business_id="biz_mock",
        business_dir="biz_mock_dir",
        readme_text="",
        tables=[],
        files=["orders.xlsx"],
    )


# ============================================================================
# 1. Walk-in Customer Leakage Protection (unmerge_and_ffill)
# ============================================================================

def test_unmerge_and_ffill_multiple_consecutive_walk_in_customers():
    """Adversarial Test 1A: Multiple consecutive walk-in customers across distinct orders.
    Order DH1 has a customer ('Alice').
    Orders DH2, DH3, DH4 are walk-in customers with None.
    Order DH5 has a customer ('Bob').
    Orders DH6 is walk-in with None.
    None must NOT be filled from Alice or Bob.
    """
    df = pd.DataFrame({
        "Mã đơn hàng": ["DH1", "DH2", "DH3", "DH4", "DH5", "DH6"],
        "Tên khách hàng": ["Alice", None, None, None, "Bob", None],
        "Tổng tiền": [100, 200, 150, 300, 250, 180],
    })
    res = unmerge_and_ffill(df)
    assert res.loc[0, "Tên khách hàng"] == "Alice"
    assert pd.isna(res.loc[1, "Tên khách hàng"])
    assert pd.isna(res.loc[2, "Tên khách hàng"])
    assert pd.isna(res.loc[3, "Tên khách hàng"])
    assert res.loc[4, "Tên khách hàng"] == "Bob"
    assert pd.isna(res.loc[5, "Tên khách hàng"])


def test_unmerge_and_ffill_mixed_merged_and_unmerged_orders():
    """Adversarial Test 1B: Order with multiple line items followed by walk-in multi-line order.
    DH1 (Alice): 2 items (row 0 has DH1 & Alice, row 1 is merged child None)
    DH2 (Walk-in None): 2 items (row 2 has DH2 & None, row 3 is merged child None)
    Row 1 must inherit Alice; row 3 must remain None and NEVER inherit Alice!
    """
    df = pd.DataFrame({
        "Mã hóa đơn": ["HD01", None, "HD02", None],
        "Khách hàng": ["Nguyễn Văn A", None, None, None],
        "Mặt hàng": ["Bánh", "Kẹo", "Nước ngọt", "Snack"],
        "Thành tiền": [10000, 20000, 15000, 25000],
    })
    res = unmerge_and_ffill(df)
    # Group 1 (HD01) child inherits parent customer
    assert res.loc[0, "Khách hàng"] == "Nguyễn Văn A"
    assert res.loc[1, "Khách hàng"] == "Nguyễn Văn A"
    assert res.loc[1, "Mã hóa đơn"] == "HD01"
    # Group 2 (HD02) walk-in must remain null across both rows
    assert res.loc[2, "Mã hóa đơn"] == "HD02"
    assert res.loc[3, "Mã hóa đơn"] == "HD02"
    assert pd.isna(res.loc[2, "Khách hàng"])
    assert pd.isna(res.loc[3, "Khách hàng"])


def test_unmerge_and_ffill_with_explicit_ffill_cols_preserves_walk_in():
    """Adversarial Test 1C: Even when ffill_cols=['Tên khách'] is explicitly passed,
    order grouping by detected_id prevents leakage across distinct unmerged orders.
    """
    df = pd.DataFrame({
        "Mã đơn": ["D1", "D2", "D3"],
        "Tên khách": ["Khách 1", None, "Khách 3"],
    })
    res = unmerge_and_ffill(df, ffill_cols=["Tên khách"])
    assert res.loc[0, "Tên khách"] == "Khách 1"
    assert pd.isna(res.loc[1, "Tên khách"])
    assert res.loc[2, "Tên khách"] == "Khách 3"


# ============================================================================
# 2. load_excel_unmerge Header & Column Name Preservation
# ============================================================================

def test_load_excel_unmerge_preserves_custom_vietnamese_column_headers(tmp_path):
    """Adversarial Test 2A: Verify default header=0 preserves unicode column headers with accents."""
    excel_path = tmp_path / "orders_vn.xlsx"
    df_src = pd.DataFrame({
        "Mã chứng từ": ["CT001", "CT002"],
        "Tên khách hàng": ["Lê Thị B", None],
        "Số tiền nợ (VNĐ)": [150000, 0],
    })
    df_src.to_excel(excel_path, index=False)

    df_loaded = load_excel_unmerge(excel_path)
    assert list(df_loaded.columns) == ["Mã chứng từ", "Tên khách hàng", "Số tiền nợ (VNĐ)"]
    assert df_loaded["Mã chứng từ"].iloc[0] == "CT001"
    assert pd.isna(df_loaded["Tên khách hàng"].iloc[1])


def test_load_excel_unmerge_header_none_and_custom(tmp_path):
    """Adversarial Test 2B: Verify passing header=None or header=1 behaves as expected."""
    excel_path = tmp_path / "orders_multi_header.xlsx"
    # Row 0: metadata title, Row 1: column headers, Row 2+: data
    data = [
        ["BÁO CÁO BÁN HÀNG THÁNG 5", None, None],
        ["Mã đơn", "Tên khách", "Tiền"],
        ["DH01", "Khách A", 50000],
        ["DH02", None, 75000],
    ]
    pd.DataFrame(data).to_excel(excel_path, index=False, header=False)

    # When header=1 is passed, row 1 becomes header
    df_h1 = load_excel_unmerge(excel_path, header=1)
    assert list(df_h1.columns) == ["Mã đơn", "Tên khách", "Tiền"]
    assert df_h1["Mã đơn"].iloc[0] == "DH01"
    assert pd.isna(df_h1["Tên khách"].iloc[1])

    # When header=None is passed, numeric columns are returned
    df_none = load_excel_unmerge(excel_path, header=None)
    assert list(df_none.columns) == [0, 1, 2]
    assert df_none.iloc[1, 0] == "Mã đơn"


def test_load_excel_unmerge_multi_sheet_dict(tmp_path):
    """Adversarial Test 2C: Verify sheet_name=None returns dict of unmerged DataFrames."""
    excel_path = tmp_path / "multi_sheet.xlsx"
    with pd.ExcelWriter(excel_path) as writer:
        pd.DataFrame({
            "Mã đơn": ["D1", None],
            "Khách": ["A", None],
            "Mặt hàng": ["Item 1", "Item 2"],
        }).to_excel(writer, sheet_name="S1", index=False)
        pd.DataFrame({
            "Mã đơn": ["D2", "D3"],
            "Khách": ["B", None],
            "Mặt hàng": ["Item 3", "Item 4"],
        }).to_excel(writer, sheet_name="S2", index=False)

    sheets = load_excel_unmerge(excel_path, sheet_name=None)
    assert isinstance(sheets, dict)
    assert "S1" in sheets and "S2" in sheets
    # S1 was merged: D1 filled
    assert sheets["S1"]["Mã đơn"].tolist() == ["D1", "D1"]
    assert sheets["S1"]["Khách"].tolist() == ["A", "A"]
    # S2 was unmerged: D3 walk-in preserved
    assert sheets["S2"]["Mã đơn"].tolist() == ["D2", "D3"]
    assert pd.isna(sheets["S2"]["Khách"].iloc[1])


# ============================================================================
# 3. Solver Guardrail Formatted Debt Strings & Zero Debt Blockers
# ============================================================================

def test_eval_guard_formatted_string_debt_accepted(empty_profile):
    """Adversarial Test 3A: Debt tables with various formatted string representations of positive debt
    must be ACCEPTED and NOT trigger Pattern 2 guardrail.
    """
    formatted_variants = [
        "150000",
        "150,000",
        " 150000 ",
        "150.000",
        "150,000.50",
        "150.000,50",
        "2,500,000",
        "100.000.000",
    ]
    for debt_str in formatted_variants:
        table_ans = {
            "columns": ["Khách hàng", "Số tiền còn nợ"],
            "rows": [["KH_01", debt_str]],
        }
        issue = _eval_guard_issue(
            question="Danh sách khách hàng còn nợ tiền?",
            answer_type="table",
            answer=table_ans,
            check=None,
            had_read_error=False,
            profile=empty_profile,
        )
        assert issue is None, f"Incorrectly flagged valid formatted debt string '{debt_str}': {issue}"


def test_eval_guard_numpy_scalar_debt_accepted(empty_profile):
    """Adversarial Test 3B: Numpy integers and floats for debt must be accepted."""
    table_ans = {
        "columns": ["Mã KH", "Dư nợ"],
        "rows": [["KH1", np.int64(250000)], ["KH2", np.float64(180500.0)]],
    }
    issue = _eval_guard_issue(
        question="Ai còn nợ nhiều nhất?",
        answer_type="table",
        answer=table_ans,
        check=None,
        had_read_error=False,
        profile=empty_profile,
    )
    assert issue is None, f"Failed on numpy debt values: {issue}"


def test_eval_guard_all_zero_debt_table_adversarial_formats_blocked(empty_profile):
    """Adversarial Test 3C: All-zero debt tables with any zero representations (int, float, string)
    must trigger Pattern 2 guard error.
    """
    zero_variants = [
        [0, 0],
        [0.0, 0.0],
        ["0", "0"],
        ["0.0", "0.0"],
        ["0,0", "0,00"],
        [" 0 ", "0.00"],
        ["00", "000"],
    ]
    for z1, z2 in zero_variants:
        table_ans = {
            "columns": ["Tên khách", "Tiền nợ"],
            "rows": [["Khách A", z1], ["Khách B", z2]],
        }
        issue = _eval_guard_issue(
            question="Bảng danh sách khách nợ tiền",
            answer_type="table",
            answer=table_ans,
            check=None,
            had_read_error=False,
            profile=empty_profile,
        )
        assert issue is not None, f"Failed to block all-zero debt table with ({z1}, {z2})"
        assert "Bảng kết quả công nợ chứa toàn số 0 hoặc số không dương" in issue


def test_eval_guard_negative_debt_table_blocked(empty_profile):
    """Adversarial Test 3D: A table with only negative or zero debt values must be blocked.
    Rulebook requires positive outstanding debt (> 0).
    """
    table_ans = {
        "columns": ["Khách hàng", "Công nợ"],
        "rows": [["KH1", "-50,000"], ["KH2", "-100000"], ["KH3", "0"]],
    }
    issue = _eval_guard_issue(
        question="Bảng tổng hợp công nợ khách hàng",
        answer_type="table",
        answer=table_ans,
        check=None,
        had_read_error=False,
        profile=empty_profile,
    )
    assert issue is not None
    assert "Bảng kết quả công nợ chứa toàn số 0 hoặc số không dương" in issue


def test_eval_guard_mixed_zero_and_positive_debt_accepted(empty_profile):
    """Adversarial Test 3E: If at least one row has positive debt (>0), table is NOT all-zero and accepted."""
    table_ans = {
        "columns": ["Khách hàng", "Dư nợ"],
        "rows": [["KH1", "0"], ["KH2", "150,000"]],
    }
    issue = _eval_guard_issue(
        question="Top khách nợ tiền",
        answer_type="table",
        answer=table_ans,
        check=None,
        had_read_error=False,
        profile=empty_profile,
    )
    assert issue is None


# ============================================================================
# 4. Solver Guardrail String Zeros in Lists
# ============================================================================

def test_eval_guard_string_zeros_list_all_variations_blocked(empty_profile):
    """Adversarial Test 4A: Various formats of zero strings in lists for debt or flow queries
    must trigger Pattern 1 guard error.
    """
    zero_lists = [
        ["0", "0"],
        ["0.0", "0.0"],
        ["0,0", "0,00"],
        [" 0 ", " 0.0 "],
        ["-0", "0"],
        ["-0.0", "0.0"],
        ["000", "0.000"],
        [np.int64(0), "0.0"],
        [0.0, "0,0"],
    ]
    for zl in zero_lists:
        issue = _eval_guard_issue(
            question="Số tiền nợ phát sinh và tiền đã trả của khách là bao nhiêu?",
            answer_type="list",
            answer=zl,
            check=None,
            had_read_error=False,
            profile=empty_profile,
        )
        assert issue is not None, f"Failed to block zero list: {zl}"
        assert "Danh sách kết quả toàn số 0 ([0, 0] hoặc tương tự)" in issue


def test_eval_guard_non_zero_or_non_flow_list_not_blocked(empty_profile):
    """Adversarial Test 4B: Lists with non-zero values or queries without debt/flow keywords
    must NOT be blocked by Pattern 1.
    """
    # Non-zero in debt query
    issue1 = _eval_guard_issue(
        question="Số tiền nợ phát sinh và tiền đã trả?",
        answer_type="list",
        answer=["0", "500000"],
        check=None,
        had_read_error=False,
        profile=empty_profile,
    )
    assert issue1 is None

    # Zeros in query not mentioning debt or flow (e.g. coordinates or non-financial counts)
    issue2 = _eval_guard_issue(
        question="Tọa độ x và y của điểm bắt đầu?",
        answer_type="list",
        answer=["0", "0"],
        check=None,
        had_read_error=False,
        profile=empty_profile,
    )
    assert issue2 is None


# ============================================================================
# 5. Sandbox Parity & Protocol End-to-End Execution
# ============================================================================

def test_sandbox_runtime_unmerge_and_ffill_no_leakage(tmp_path):
    """Adversarial Test 5: Execute unmerge_and_ffill inside the actual sandbox runtime
    to guarantee the injected runtime helper has exact behavioral parity.
    """
    code = (
        "import json, pandas as pd\n"
        "df = pd.DataFrame({\n"
        "    'Mã đơn hàng': ['DH10', 'DH11', 'DH12'],\n"
        "    'Tên khách hàng': ['Nguyễn Thị Hương', None, None],\n"
        "    'Số tiền': [120000, 250000, 300000]\n"
        "})\n"
        "res = unmerge_and_ffill(df)\n"
        "assert res.loc[0, 'Tên khách hàng'] == 'Nguyễn Thị Hương'\n"
        "assert pd.isna(res.loc[1, 'Tên khách hàng'])\n"
        "assert pd.isna(res.loc[2, 'Tên khách hàng'])\n"
        "print(json.dumps({'kind': 'final', 'type': 'boolean', 'answer': True, 'evidence': 'sandbox verified'}))\n"
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
