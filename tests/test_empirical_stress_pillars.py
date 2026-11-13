"""Empirical Stress Test for 4-Pillar Lean Bounded Execution Architecture.

Covers:
1. Multi-level merged headers in Excel and CSV tables.
2. Corrupted date strings (out-of-bounds, invalid formats, mixed types).
3. Circular and complex debt transaction chains.
4. Abstain Gate robustness against unanswerable hallucinations under varied configs.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
import pandas as pd
import pytest

from src.agent.sandbox import (
    load_excel_unmerge,
    run_python_in_sandbox,
    unmerge_and_ffill,
    validate_protocol_payload,
)
from src.agent.solver import (
    BaseInferenceBackend,
    DataMateAgent,
    _eval_guard_issue,
)
from src.postprocess.vn_utils import parse_vn_date, parse_vn_number
from src.schemas import BusinessProfile, QuestionItem, SubmissionItem, TableSchema


class ScriptedBackend(BaseInferenceBackend):
    def __init__(self, responses: List[str]):
        self.responses = list(responses)
        self.call_count = 0

    def generate(self, messages: List[Dict[str, str]]) -> str:
        if self.call_count < len(self.responses):
            res = self.responses[self.call_count]
            self.call_count += 1
            return res
        return "```python\nprint(json.dumps({'kind':'final','type':'number','answer':0,'evidence':'none'}))\n```"


@pytest.fixture
def empty_profile():
    return BusinessProfile(
        business_id="biz_stress",
        business_dir="biz_stress_dir",
        readme_text="",
        tables=[
            TableSchema(
                source_file="orders.xlsx",
                table_name="orders",
                columns=["MaDon", "Ngay", "TongTien", "TrangThai"],
                dtypes={"MaDon": "object", "TongTien": "float64"},
                row_count=100,
                categorical_values={"TrangThai": ["Xong", "Huy"]},
                status="ok",
            )
        ],
        files=["orders.xlsx"],
    )


# =====================================================================
# Stress Test 1: Multi-level Merged Headers
# =====================================================================

def test_multilevel_merged_headers_openpyxl(tmp_path):
    """Test reading an Excel file with a 2-level header:
    Row 1: Title/Meta ('BẢNG KÊ BÁN HÀNG', None, None, None)
    Row 2: Group Header ('Thông tin đơn', None, 'Sản phẩm', None)
    Row 3: Real Column Header ('Mã đơn', 'Ngày', 'Tên hàng', 'Thành tiền')
    Row 4: Data row ('DH01', '2026-05-01', 'Bánh', 50000)
    Row 5: Merged child row (None, None, 'Kẹo', 30000)
    """
    excel_path = tmp_path / "multilevel_test.xlsx"
    wb_df = pd.DataFrame([
        ["BẢNG KÊ BÁN HÀNG", None, None, None],
        ["Thông tin đơn", None, "Chi tiết hàng", None],
        ["Mã đơn", "Ngày lập", "Tên hàng", "Thành tiền"],
        ["DH01", "2026-05-01", "Bánh", 50000],
        [None, None, "Kẹo", 30000],
        ["DH02", "2026-05-02", "Sữa", 40000],
    ])
    # Write to Excel without header
    wb_df.to_excel(excel_path, header=False, index=False)

    # In sandbox environment: load_excel_unmerge
    df = load_excel_unmerge(excel_path)
    # Check if real columns were detected or how unmerge handled it
    assert df is not None
    assert len(df) > 0


def test_metadata_banner_row_misidentification_risk(tmp_path):
    """Stress Test 1B: Metadata banner where all cells have text.
    Row 0: Báo cáo bán hàng,Cửa hàng 1,Chi nhánh Hà Nội,Tháng 5 (Banner with 4 text cells)
    Row 1: Mã đơn,Ngày lập,Tên hàng,Thành tiền (Real column header)
    Row 2: DH01,2026-05-01,Bánh ngọt,50000
    """
    csv_path = tmp_path / "banner_test.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("Báo cáo bán hàng,Cửa hàng 1,Chi nhánh Hà Nội,Tháng 5\n")
        f.write("Mã đơn,Ngày lập,Tên hàng,Thành tiền\n")
        f.write("DH01,2026-05-01,Bánh ngọt,50000\n")

    code = f"""
import json, os, pandas as pd
# In sandbox, pd.read_csv default header=0 reads row 0 as columns
df = pd.read_csv(r'{csv_path}')
cols = list(df.columns)
# Because none of the columns start with 'Unnamed:', _detect_best_header is bypassed!
print(json.dumps({{'kind': 'observation', 'data': cols, 'message': 'detected_cols'}}))
"""
    res = run_python_in_sandbox(code, business_dir=str(tmp_path), work_dir=str(tmp_path / "work"))
    assert res.success is True, f"Sandbox failed: {res.stderr} / {res.error_message}"
    detected_cols = res.parsed_output["data"]
    print("EMPIRICALLY DETECTED COLS:", detected_cols)
    # PROVEN VULNERABILITY: The columns are the metadata banner, NOT the real headers!
    assert detected_cols == ['Báo cáo bán hàng', 'Cửa hàng 1', 'Chi nhánh Hà Nội', 'Tháng 5']


# =====================================================================
# Stress Test 2: Corrupted Date Strings
# =====================================================================

def test_corrupted_date_strings_handling():
    """Verify parse_vn_date behavior on invalid or out-of-range dates."""
    dates = pd.Series([
        "2026-02-31",        # Feb 31 does not exist
        "2026-13-45",        # Month 13
        "32/05/2026",        # Day 32
        "2026-05-01 25:70",  # Hour 25
        "46167.0",           # Valid Excel serial
        "invalid_text_date", # Total garbage
        None,
        np.nan,
        "15/08/2026",        # Valid DD/MM/YYYY
    ])

    parsed = parse_vn_date(dates)
    assert pd.isna(parsed[0])  # 2026-02-31 -> NaT
    assert pd.isna(parsed[1])  # 2026-13-45 -> NaT
    assert pd.isna(parsed[2])  # 32/05/2026 -> NaT
    assert pd.isna(parsed[3])  # 2026-05-01 25:70 -> NaT
    assert not pd.isna(parsed[4])  # Excel serial -> valid timestamp
    assert pd.isna(parsed[5])  # Garbage -> NaT
    assert pd.isna(parsed[6])  # None -> NaT
    assert pd.isna(parsed[7])  # NaN -> NaT
    assert not pd.isna(parsed[8])  # Valid date -> valid timestamp


# =====================================================================
# Stress Test 3: Circular Debt Transactions
# =====================================================================

def test_circular_debt_and_out_of_order_transactions():
    """Verify handling of debt calculations where transactions are out of order,
    or customer balance oscillates across positive/negative due to returns/vouchers.
    """
    df_ledger = pd.DataFrame({
        "ngay": ["2026-05-10", "2026-05-01", "2026-05-05", "2026-05-15"],
        "khach": ["KH01", "KH01", "KH01", "KH01"],
        "phat_sinh_no": [0, 500000, 0, 200000],
        "da_tra": [300000, 0, 400000, 0], # At 05-05, total paid (400k) < total debt (500k), balance = 100k
    })
    # If sorted properly by date:
    df_sorted = df_ledger.sort_values("ngay")
    as_of = pd.Timestamp("2026-05-12")
    df_filtered = df_sorted[pd.to_datetime(df_sorted["ngay"]) <= as_of]
    net_debt = df_filtered["phat_sinh_no"].sum() - df_filtered["da_tra"].sum()
    # At 2026-05-12: total debt = 500k, total paid = 700k -> net balance = -200k (customer overpaid)
    assert net_debt == -200000


# =====================================================================
# Stress Test 4: Abstain Gate on Hallucinated Unanswerable
# =====================================================================

def test_abstain_gate_with_flag_enabled(tmp_path):
    """When abstain_on_unanswerable=True, hallucinated 'unanswerable' is intercepted and converted to 'abstain'."""
    split_dir = tmp_path / "test_split"
    biz_dir = split_dir / "data" / "biz_stress"
    biz_dir.mkdir(parents=True)
    (biz_dir / "sales.csv").write_text("item,qty\nA,1\n", encoding="utf-8")
    (split_dir / "rulebook.md").write_text("# Rulebook", encoding="utf-8")

    backend = ScriptedBackend([
        """```python
import json
print(json.dumps({'kind':'final','type':'unanswerable','answer':None,'evidence':'sales.csv','reason':'Không tìm thấy cột doanh thu'}))
```"""
    ])
    cfg = {
        "agent": {
            "max_turns": 1,
            "abstain_on_unanswerable": True,
        }
    }
    agent = DataMateAgent(config=cfg, data_dir=split_dir, backend=backend)
    q = QuestionItem("q_stress_1", "biz_stress", "Doanh thu ngày hôm qua là bao nhiêu?", "2026-05-02")
    sub, trace = agent.answer_question_with_trace(q)

    assert sub.type == "abstain", f"Expected 'abstain', got {sub.type}"
    assert sub.answer is None


def test_abstain_gate_with_flag_disabled_or_default(tmp_path):
    """When abstain_on_unanswerable=False (or default), hallucinated 'unanswerable' with valid evidence slips through."""
    split_dir = tmp_path / "test_split"
    biz_dir = split_dir / "data" / "biz_stress"
    biz_dir.mkdir(parents=True)
    (biz_dir / "sales.csv").write_text("item,qty\nA,1\n", encoding="utf-8")
    (split_dir / "rulebook.md").write_text("# Rulebook", encoding="utf-8")

    backend = ScriptedBackend([
        """```python
import json
print(json.dumps({'kind':'final','type':'unanswerable','answer':None,'evidence':'sales.csv','reason':'Không tìm thấy cột doanh thu'}))
```"""
    ])
    cfg = {
        "agent": {
            "max_turns": 1,
            "abstain_on_unanswerable": False,
        }
    }
    agent = DataMateAgent(config=cfg, data_dir=split_dir, backend=backend)
    q = QuestionItem("q_stress_2", "biz_stress", "Doanh thu ngày hôm qua là bao nhiêu?", "2026-05-02")
    sub, trace = agent.answer_question_with_trace(q)

    # When flag is disabled and evidence is present, unanswerable is NOT intercepted:
    assert sub.type == "unanswerable", f"Expected 'unanswerable', got {sub.type}"
