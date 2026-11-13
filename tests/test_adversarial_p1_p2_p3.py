"""Empirical and Adversarial Stress Test Suite for DataMate P1, P2, P3 Hardening.

Constructed by Teamwork Challenger to empirically verify:
- P1: Context capping boundaries, massive schemas, dirty columns, mixed types, sheet grouping.
- P2: Zero acceptance/rejection logic, hallucination blockers, abstain gate under crashes/timeouts.
- P3: Unmerge/ffill edge cases, leap year boundary dates for 'cùng kỳ tháng trước', prompt injection.
"""

import json
import math
import unicodedata
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from src.agent.prompts import build_user_prompt
from src.agent.sandbox import (
    load_excel_unmerge,
    run_python_in_sandbox,
    strip_accents,
    unmerge_and_ffill,
)
from src.agent.solver import (
    DataMateAgent,
    _eval_guard_issue,
    resolve_business_path,
)
from src.profiler.business_loader import (
    MAX_EXHAUSTIVE_CARDINALITY,
    MAX_SAMPLE_CATEGORICAL,
    MAX_SCHEMA_CHARS,
    _extract_df_schema,
    _is_excluded_value_column,
    _profile_dataframe_categoricals,
    format_eval_schema,
    format_profile_for_prompt,
    profile_business_package,
)
from src.schemas import (
    AnswerType,
    BusinessProfile,
    QuestionItem,
    SubmissionItem,
    TableSchema,
)
from src.time_resolver.calendar_utils import resolve_relative_dates


# =====================================================================
# P1 ADVERSARIAL TESTS (business_loader.py)
# =====================================================================

class TestP1Adversarial:
    """Stress tests and boundary checks for P1 profiling and context capping."""

    def test_schema_context_capping_hard_boundary(self):
        """Ensure schema output NEVER exceeds MAX_SCHEMA_CHARS even with massive schemas."""
        tables = []
        for i in range(100):
            cols = [f"col_{j}_{i}" for j in range(20)]
            cat_vals = {f"col_{j}_{i}": [f"long_label_name_value_{k}" for k in range(15)] for j in range(8)}
            u_counts = {f"col_{j}_{i}": 15 for j in range(8)}
            t = TableSchema(
                source_file=f"massive_file_{i}.xlsx",
                table_name=f"sheet_{i}",
                columns=cols,
                dtypes={c: "object" for c in cols},
                row_count=50000,
                categorical_values=cat_vals,
                status="ok",
                column_unique_counts=u_counts,
                exhaustive_columns=list(cat_vals.keys()),
            )
            tables.append(t)

        rendered = format_eval_schema(tables)
        assert len(rendered) <= MAX_SCHEMA_CHARS, (
            f"Rendered schema ({len(rendered)} chars) exceeded limit {MAX_SCHEMA_CHARS}"
        )
        assert "... [Cắt bớt do vượt trần token schema]" in rendered

    def test_dirty_columns_mixed_types_and_extremes(self):
        """Profile DataFrame containing mixed types, NaNs, infinities, multiline text, and weird dtypes."""
        df_dirty = pd.DataFrame({
            "col_mixed": [1, "chuỗi tiếng Việt", 3.14, None, np.nan, [1, 2], {"dict": 1}],
            "col_all_nan": [None, np.nan, float("nan"), None, None, None, None],
            "col_whitespace": ["", "   ", "\n\r", "\t\t", "  ", "", "  "],
            "col_vietnamese_accents": [
                "Đã giao hàng", "đang xử lý", "HỦY ĐƠN", "Đã giao hàng",
                "Chờ thanh toán", "Đã giao hàng", "Trả hàng",
            ],
            "col_special_chars": ["Tag#1", "Tag<2>", 'Text"with"quotes', "Slash/Path", "Back\\slash", "Emoji☕", "Line\nBreak"],
            "col_boolean": [True, False, True, True, False, False, True],
            "col_numbers": [100, 200, 100, 300, 200, 100, 400],
        })

        cat_vals, u_counts, exh_cols, trunc_cat = _profile_dataframe_categoricals(df_dirty)

        # All-NaN column should not produce categorical values
        assert "col_all_nan" not in cat_vals

        # Whitespace-only column should not produce valid categorical values
        assert "col_whitespace" not in cat_vals

        # Vietnamese accents should be properly detected
        assert "col_vietnamese_accents" in cat_vals
        assert u_counts["col_vietnamese_accents"] == 5
        assert "col_vietnamese_accents" in exh_cols

        # col_numbers with <= 5 unique values is small int enum
        assert "col_numbers" in cat_vals
        assert u_counts["col_numbers"] == 4

    def test_empty_and_single_row_dataframes(self):
        """Edge cases: completely empty DataFrame, DataFrame with columns but no rows, 1 row."""
        # 1. Zero rows, zero columns
        df_empty_0 = pd.DataFrame()
        schema_0 = _extract_df_schema(df_empty_0, "empty.csv", "empty")
        assert schema_0.row_count == 0
        assert schema_0.columns == []
        assert schema_0.categorical_values == {}

        # 2. Zero rows, but defined columns
        df_empty_cols = pd.DataFrame(columns=["MaDon", "TrangThai", "Ngay"])
        schema_cols = _extract_df_schema(df_empty_cols, "empty_cols.csv", "empty_cols")
        assert schema_cols.row_count == 0
        assert len(schema_cols.columns) == 3
        assert schema_cols.categorical_values == {}

        # 3. Single row DataFrame
        df_single = pd.DataFrame({"MaDon": ["DH001"], "TrangThai": ["Hoàn thành"], "Tien": [50000]})
        schema_single = _extract_df_schema(df_single, "single.csv", "single")
        assert schema_single.row_count == 1
        assert schema_single.categorical_values["TrangThai"] == ["Hoàn thành"]
        assert schema_single.column_unique_counts["TrangThai"] == 1

    def test_sheet_grouping_identical_vs_differing(self):
        """Test sheet deduplication: identical schemas grouped, differing schemas preserved."""
        t1 = TableSchema(source_file="Shop.xlsx", table_name="T01", columns=["Ma", "Ten", "Gia"], dtypes={}, row_count=10)
        t2 = TableSchema(source_file="Shop.xlsx", table_name="T02", columns=["Ma", "Ten", "Gia"], dtypes={}, row_count=10)
        t3 = TableSchema(source_file="Shop.xlsx", table_name="T03", columns=["Ma", "Ten", "Gia"], dtypes={}, row_count=10)
        t4 = TableSchema(source_file="Shop.xlsx", table_name="T04", columns=["Ma", "Ten", "Gia"], dtypes={}, row_count=10)

        # Differing schemas
        t_diff_order = TableSchema(source_file="Shop.xlsx", table_name="T_Order", columns=["Ten", "Ma", "Gia"], dtypes={}, row_count=10)
        t_diff_extra = TableSchema(source_file="Shop.xlsx", table_name="T_Extra", columns=["Ma", "Ten", "Gia", "VAT"], dtypes={}, row_count=10)
        t_diff_header = TableSchema(source_file="Shop.xlsx", table_name="T_Hdr", columns=["Ma", "Ten", "Gia"], dtypes={}, row_count=10, candidate_header_row=2)

        tables = [t1, t2, t3, t4, t_diff_order, t_diff_extra, t_diff_header]
        rendered = format_eval_schema(tables)

        # 4 identical sheets should be consolidated
        assert "4 sheets cùng cấu trúc" in rendered
        assert "'T01', ..., 'T04'" in rendered

        # Differing sheets must appear separately
        assert "'T_Order'" in rendered
        assert "'T_Extra'" in rendered
        assert "'T_Hdr'" in rendered

    def test_sqlite_special_identifiers_profiling(self, tmp_path):
        """Profile SQLite database containing table and column names with spaces, dashes, and quotes."""
        import sqlite3
        db_path = tmp_path / "shop_special.sqlite"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute('CREATE TABLE "Don Hang - Chi Tiet" ("Ma Don" TEXT, "Trang Thai" TEXT, "Tien" REAL);')
        cur.execute('INSERT INTO "Don Hang - Chi Tiet" VALUES ("DH01", "Hoàn thành", 150000);')
        cur.execute('INSERT INTO "Don Hang - Chi Tiet" VALUES ("DH02", "Đã hủy", 200000);')
        conn.commit()
        conn.close()

        prof = profile_business_package(tmp_path, "biz_special")
        assert len(prof.tables) == 1
        t = prof.tables[0]
        assert t.table_name == "Don Hang - Chi Tiet"
        assert t.columns == ["Ma Don", "Trang Thai", "Tien"]
        assert t.status == "ok"
        assert "Trang Thai" in t.categorical_values
        assert set(t.categorical_values["Trang Thai"]) == {"Hoàn thành", "Đã hủy"}


# =====================================================================
# P2 ADVERSARIAL TESTS (solver.py)
# =====================================================================

class TestP2Adversarial:
    """Stress tests for solver zero validation, hallucination blockers, and Abstain Gate."""

    @pytest.fixture
    def sample_profile(self):
        t = TableSchema(
            source_file="don_hang.xlsx",
            table_name="DonHang",
            columns=["MaDon", "DoanhThu", "TrangThai"],
            dtypes={"MaDon": "object", "DoanhThu": "int64", "TrangThai": "object"},
            row_count=500,
        )
        return BusinessProfile(
            business_id="biz_test",
            business_dir="",
            readme_text="",
            tables=[t],
        )

    def test_zero_validation_spurious_vs_verified(self, sample_profile):
        """Stress-test zero validation: spurious zeros flagged, properly verified zeros accepted."""
        q_revenue = "Tổng doanh thu tháng 7 là bao nhiêu?"

        # 1. Zero without any check -> MUST be flagged
        issue_unverified = _eval_guard_issue(
            q_revenue, "number", 0, check=None, had_read_error=False, profile=sample_profile
        )
        assert issue_unverified is not None
        assert "chưa có bằng chứng xác minh" in issue_unverified

        # 2. Zero with empty check dict or missing detail -> MUST be flagged
        issue_no_detail = _eval_guard_issue(
            q_revenue, "number", 0, check={"verified_zero": True}, had_read_error=False, profile=sample_profile
        )
        assert issue_no_detail is not None

        # 3. Zero with valid check detail and verified_zero=True -> MUST BE ACCEPTED
        issue_verified = _eval_guard_issue(
            q_revenue, "number", 0,
            check={"verified_zero": True, "detail": "Shop mới mở ngày 01/08, tháng 7 chưa kinh doanh"},
            had_read_error=False, profile=sample_profile
        )
        assert issue_verified is None

        # 4. Zero with rows_after_filter > 0 -> MUST BE ACCEPTED
        issue_zero_sum = _eval_guard_issue(
            q_revenue, "number", 0,
            check={"source_file": "don_hang.xlsx", "rows_after_filter": 5, "detail": "Các đơn đều có voucher 100%"},
            had_read_error=False, profile=sample_profile
        )
        assert issue_zero_sum is None

        # 5. Non-suspicious zero (e.g. unsold items) does not require check
        q_unsold = "Có bao nhiêu mặt hàng ế ẩm không ai mua?"
        issue_unsold = _eval_guard_issue(
            q_unsold, "number", 0, check=None, had_read_error=False, profile=sample_profile
        )
        assert issue_unsold is None

    def test_hallucination_blocker_all_zero_lists(self, sample_profile):
        """Block hallucinated [0, 0] or [0, 0, 0] responses."""
        q_debt = "Khách hàng còn nợ bao nhiêu tiền?"

        # [0, 0] -> Blocked
        assert _eval_guard_issue(q_debt, "list", [0, 0], None, False, sample_profile) is not None
        # [0.0, 0.0] -> Blocked
        assert _eval_guard_issue(q_debt, "list", [0.0, 0.0], None, False, sample_profile) is not None
        # [0, 0, 0] -> Blocked
        assert _eval_guard_issue(q_debt, "list", [0, 0, 0], None, False, sample_profile) is not None

        # Legitimate non-zero or mixed list -> Allowed
        assert _eval_guard_issue(q_debt, "list", [0, 50000], None, False, sample_profile) is None
        assert _eval_guard_issue(q_debt, "list", ["Khách A", "Khách B"], None, False, sample_profile) is None

    def test_hallucination_blocker_zero_debt_tables(self, sample_profile):
        """Table with only zero/negative debt must be blocked; positive debt allowed."""
        q_debt = "Bảng danh sách công nợ khách hàng hiện tại"

        # Table with numeric 0 debt -> Blocked
        tbl_zero = {"columns": ["Khách", "Nợ"], "rows": [["Nguyễn Văn A", 0], ["Trần Thị B", 0]]}
        issue_tbl_0 = _eval_guard_issue(q_debt, "table", tbl_zero, None, False, sample_profile)
        assert issue_tbl_0 is not None
        assert "toàn số 0 hoặc số không dương" in issue_tbl_0

        # Table with negative debt only -> Blocked
        tbl_neg = {"columns": ["Khách", "Nợ"], "rows": [["Nguyễn Văn A", -20000]]}
        issue_tbl_neg = _eval_guard_issue(q_debt, "table", tbl_neg, None, False, sample_profile)
        assert issue_tbl_neg is not None

        # Table with valid positive numeric debt -> Allowed
        tbl_valid = {"columns": ["Khách", "Nợ"], "rows": [["Nguyễn Văn A", 150000]]}
        assert _eval_guard_issue(q_debt, "table", tbl_valid, None, False, sample_profile) is None

    def test_hallucination_blocker_debt_with_string_numbers_vulnerability(self, sample_profile):
        """Verify table with positive debt formatted as string (e.g. '150000') is accepted by guard."""
        q_debt = "Bảng danh sách công nợ khách hàng hiện tại"
        tbl_str_positive = {"columns": ["Khách", "Tiền nợ"], "rows": [["Khách A", "150000"], ["Khách B", "250000"]]}
        issue = _eval_guard_issue(q_debt, "table", tbl_str_positive, None, False, sample_profile)
        # String-formatted positive debt must be accepted (issue is None)
        assert issue is None, "String-formatted positive debt must not trigger false rejection"

    def test_hallucination_blocker_duplicate_rankings(self, sample_profile):
        """Ranking lists/tables with duplicate entities must be blocked."""
        q_rank = "Top 3 sản phẩm bán chạy nhất trong tháng"

        # Exact duplicate
        assert _eval_guard_issue(q_rank, "list", ["Mì tôm", "Mì tôm", "Bánh mì"], None, False, sample_profile) is not None

        # Case-insensitive duplicate
        assert _eval_guard_issue(q_rank, "list", ["Mì tôm", "mì tôm", "Bánh mì"], None, False, sample_profile) is not None

        # NFC vs NFD unicode duplicate
        nfc_str = "Cà phê sữa"
        nfd_str = unicodedata.normalize("NFD", nfc_str)
        assert _eval_guard_issue(q_rank, "list", [nfc_str, nfd_str, "Trà chanh"], None, False, sample_profile) is not None

        # Table duplicate first column
        tbl_dup = {
            "columns": ["Mặt hàng", "Doanh thu"],
            "rows": [["Mì tôm", 100000], ["Mì tôm", 80000], ["Bánh mì", 50000]],
        }
        assert _eval_guard_issue(q_rank, "table", tbl_dup, None, False, sample_profile) is not None

        # Valid distinct ranking -> Allowed
        assert _eval_guard_issue(q_rank, "list", ["Mì tôm", "Bánh mì", "Trà sữa"], None, False, sample_profile) is None

    def test_hallucination_blocker_duplicate_rankings_unaccented_gap(self, sample_profile):
        """FINDING PROBE: Duplicate ranking with unaccented variation (e.g. 'Cà phê' vs 'Ca phe').

        Currently line 766 only normalizes NFC and casefolds, but does NOT strip accents.
        Thus, 'Cà phê' and 'Ca phe' are not detected as duplicates.
        """
        q_rank = "Top 3 sản phẩm bán chạy nhất trong tháng"
        ans_unaccented = ["Cà phê", "Ca phe", "Trà sữa"]
        issue = _eval_guard_issue(q_rank, "list", ans_unaccented, None, False, sample_profile)
        # Verify that current behavior does not catch unaccented duplicates
        assert issue is None, "Documents current limitation: unaccented duplicate names are not stripped"

    def test_load_excel_unmerge_default_header_flaw(self, tmp_path):
        """Verify load_excel_unmerge defaults to header=0 like pandas, preserving column names."""
        xlsx_file = tmp_path / "test_hdr.xlsx"
        df_src = pd.DataFrame({"Mã đơn": ["DH01", None], "Trạng thái": ["Hoàn thành", None]})
        df_src.to_excel(str(xlsx_file), index=False)

        # Standard pandas behavior:
        df_pd = pd.read_excel(str(xlsx_file))
        assert list(df_pd.columns) == ["Mã đơn", "Trạng thái"]

        # load_excel_unmerge without explicit header:
        df_unmerged = load_excel_unmerge(str(xlsx_file))
        # Default header=0 preserves string column names:
        assert list(df_unmerged.columns) == ["Mã đơn", "Trạng thái"]

    def test_abstain_gate_on_unhandled_crashes(self, tmp_path):
        """If the solver backend or steps throw unexpected exceptions, return abstain (0.0 PA)."""
        biz_dir = tmp_path / "data" / "biz_test"
        biz_dir.mkdir(parents=True, exist_ok=True)
        (biz_dir / "README.md").write_text("Test shop", encoding="utf-8")

        mock_backend = MagicMock()
        mock_backend.generate.side_effect = RuntimeError("Catastrophic CUDA driver failure")

        config = {
            "model": {"name_or_path": "mock"},
            "agent": {"max_turns": 3, "eval_core_rules": True, "abstain_on_unanswerable": True},
            "paths": {"work_dir": str(tmp_path)},
        }
        agent = DataMateAgent(config=config, data_dir=tmp_path, backend=mock_backend)

        # Mock question
        item = QuestionItem(
            id="crash_q01",
            business_id="biz_test",
            question="Doanh thu là bao nhiêu?",
            as_of_date="2025-07-01",
        )

        sub, trace = agent.answer_question_with_trace(item)
        assert sub.type == AnswerType.ABSTAIN.value
        assert "Catastrophic CUDA driver failure" in (sub.reason or "") or "Backend generation error" in (sub.reason or "")
        assert trace["final_answer"]["type"] == AnswerType.ABSTAIN.value


# =====================================================================
# P3 ADVERSARIAL TESTS (sandbox.py, calendar_utils.py, prompts.py)
# =====================================================================

class TestP3Adversarial:
    """Stress tests for unmerge/ffill, relative calendar boundaries, and prompt matching."""

    def test_unmerge_and_ffill_adversarial_structures(self):
        """Stress-test unmerge_and_ffill across unusual table layouts."""
        # 1. Multiple ID columns: 'Mã đơn hàng' and 'Mã chứng từ'
        df_multi_id = pd.DataFrame({
            "Mã đơn hàng": ["DH01", None, "DH02", None],
            "Mã chứng từ": ["CT01", None, "CT02", None],
            "Tên khách": ["A", None, "B", None],
            "Mặt hàng": ["SP1", "SP2", "SP3", "SP4"],
            "Tiền": [10, 20, 30, 40],
        })
        res_multi = unmerge_and_ffill(df_multi_id)
        assert res_multi["Tên khách"].tolist() == ["A", "A", "B", "B"]
        assert res_multi["Mã đơn hàng"].tolist() == ["DH01", "DH01", "DH02", "DH02"]

        # 2. Table with NO order ID column (only customer and date)
        df_no_order_id = pd.DataFrame({
            "Tên khách": ["Nguyễn Văn A", None, "Trần Thị B", None],
            "Ngày đặt": ["2025-05-01", None, "2025-05-02", None],
            "Trạng thái": ["Hoàn thành", None, "Đã hủy", None],
            "Mặt hàng": ["Item 1", "Item 2", "Item 3", "Item 4"],
        })
        res_no_order = unmerge_and_ffill(df_no_order_id)
        assert res_no_order["Tên khách"].tolist() == ["Nguyễn Văn A", "Nguyễn Văn A", "Trần Thị B", "Trần Thị B"]
        assert res_no_order["Trạng thái"].tolist() == ["Hoàn thành", "Hoàn thành", "Đã hủy", "Đã hủy"]

        # 3. DataFrame with NO NaN rows (already flat)
        df_flat = pd.DataFrame({"Mã đơn": ["D1", "D2"], "Trạng thái": ["A", "B"]})
        res_flat = unmerge_and_ffill(df_flat)
        assert res_flat.equals(df_flat)

        # 4. DataFrame completely empty
        df_empty = pd.DataFrame()
        res_empty = unmerge_and_ffill(df_empty)
        assert res_empty.empty

    def test_leap_year_and_boundary_cung_ky_dates(self):
        """Thorough verification of relative date calculation for 'cùng kỳ tháng trước'."""
        # Test 1: Leap year boundary 2024-02-29 -> January 2024 has 31 days -> 2024-01-01 .. 2024-01-29
        rel_2024_02_29 = resolve_relative_dates("2024-02-29")
        cung_ky_key = [k for k in rel_2024_02_29 if k.startswith("cùng kỳ tháng trước")][0]
        assert rel_2024_02_29[cung_ky_key] == "2024-01-01 .. 2024-01-29"

        # Test 2: Leap year end-of-March 2024-03-31 -> February 2024 has 29 days -> 2024-02-01 .. 2024-02-29
        rel_2024_03_31 = resolve_relative_dates("2024-03-31")
        assert rel_2024_03_31[cung_ky_key] == "2024-02-01 .. 2024-02-29"

        # Test 3: Non-leap year end-of-March 2025-03-31 -> February 2025 has 28 days -> 2025-02-01 .. 2025-02-28
        rel_2025_03_31 = resolve_relative_dates("2025-03-31")
        assert rel_2025_03_31[cung_ky_key] == "2025-02-01 .. 2025-02-28"

        # Test 4: January boundary 2026-01-15 -> December of previous year -> 2025-12-01 .. 2025-12-15
        rel_2026_01_15 = resolve_relative_dates("2026-01-15")
        assert rel_2026_01_15[cung_ky_key] == "2025-12-01 .. 2025-12-15"

        # Test 5: First day of month 2025-05-01 -> 2025-04-01 .. 2025-04-01
        rel_2025_05_01 = resolve_relative_dates("2025-05-01")
        assert rel_2025_05_01[cung_ky_key] == "2025-04-01 .. 2025-04-01"

    def test_build_user_prompt_cung_ky_suppression(self):
        """Prompt builder must inject same-period interval and suppress full-prior-month interval."""
        rel_dates = resolve_relative_dates("2025-07-03")
        q = "Doanh thu tháng này tăng hay giảm bao nhiêu so với cùng kỳ tháng trước?"

        prompt = build_user_prompt(
            question=q,
            as_of_date="2025-07-03",
            relative_dates=rel_dates,
            schema_markdown="Schema: ...",
            core_rules=True,
        )

        # Same period interval must be included
        assert "2025-06-01 .. 2025-06-03" in prompt
        # Full month interval 2025-06-01 .. 2025-06-30 must NOT be included
        assert "2025-06-01 .. 2025-06-30" not in prompt
