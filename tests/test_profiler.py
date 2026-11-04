"""Unit tests for business data package profiler (.csv, .xlsx, .sqlite)."""

import sqlite3
import tempfile
from pathlib import Path
import pandas as pd
import pytest

from src.profiler.business_loader import (
    _detect_excel_header_candidate,
    format_profile_for_prompt,
    profile_business_package,
)


class TestProfiler:
    def test_csv_profiling(self, tmp_path):
        biz_dir = tmp_path / "biz_test_csv"
        biz_dir.mkdir()

        readme = biz_dir / "README.md"
        readme.write_text("Cửa hàng tạp hóa nhỏ. Bán lẻ theo lon/gói.", encoding="utf-8")

        csv_file = biz_dir / "don_hang.csv"
        df = pd.DataFrame({
            "ma_don": ["DH01", "DH02", "DH03"],
            "ngay": ["2026-08-01", "2026-08-02", "2026-08-03"],
            "so_tien": [100000, 250000, 50000],
            "loai": ["ban_le", "ban_le", "ban_si"],
        })
        df.to_csv(csv_file, index=False)

        profile = profile_business_package(biz_dir, "biz_test_csv")
        assert profile.business_id == "biz_test_csv"
        assert len(profile.tables) == 1

        tbl = profile.tables[0]
        assert tbl.source_file == "don_hang.csv"
        assert tbl.row_count == 3
        assert "ma_don" in tbl.columns
        assert "so_tien" in tbl.columns
        assert tbl.status == "ok"
        assert tbl.date_range is not None
        assert "ngay" in tbl.date_range

        md = format_profile_for_prompt(profile)
        assert "Cửa hàng tạp hóa nhỏ" in md
        assert "don_hang.csv" in md

    def test_excel_header_uncertainty_and_banner_detection(self, tmp_path):
        biz_dir = tmp_path / "biz_test_excel"
        biz_dir.mkdir()

        excel_path = biz_dir / "bao_cao.xlsx"
        raw_rows = [
            ["BẢNG KÊ THÁNG 8", None, None],
            ["Mã hàng", "Tên hàng", "Doanh thu"],
            ["SP01", "Trà xanh", 50000],
            ["SP02", "Cà phê", 70000],
        ]
        raw_df = pd.DataFrame(raw_rows)
        raw_df.to_excel(excel_path, header=False, index=False, sheet_name="BaoCao")

        profile = profile_business_package(biz_dir, "biz_test_excel")
        assert len(profile.tables) == 1
        tbl = profile.tables[0]

        assert tbl.candidate_header_row == 1
        assert tbl.header_uncertainty is True
        assert len(tbl.raw_preview) >= 2
        assert tbl.columns == ["Mã hàng", "Tên hàng", "Doanh thu"]

    def test_sqlite_safe_ro_inspection_and_truncation(self, tmp_path):
        biz_dir = tmp_path / "biz_test_sqlite"
        biz_dir.mkdir()

        db_path = biz_dir / "data.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute('CREATE TABLE "sales""archive" ("customer""name" TEXT, qty INTEGER);')
        conn.execute('INSERT INTO "sales""archive" VALUES (?, ?)', ("Lan", 2))
        conn.commit()
        conn.close()

        profile = profile_business_package(biz_dir, "biz_test_sqlite")
        assert len(profile.tables) == 1
        tbl = profile.tables[0]
        assert tbl.table_name == 'sales"archive'
        assert tbl.row_count == 1
        assert tbl.columns == ['customer"name', "qty"]
        assert tbl.status == "ok"

    def test_profiler_preserves_readable_tables_on_partial_failure(self, tmp_path):
        biz_dir = tmp_path / "biz_test_error"
        biz_dir.mkdir()

        csv_valid = biz_dir / "valid.csv"
        pd.DataFrame({"x": [1, 2]}).to_csv(csv_valid, index=False)

        bad_sqlite = biz_dir / "corrupted.sqlite"
        bad_sqlite.write_text("NOT A SQLITE DATABASE", encoding="utf-8")

        profile = profile_business_package(biz_dir, "biz_test_error")
        assert len(profile.files) == 2
        valid_tables = [t for t in profile.tables if t.status == "ok"]
        error_tables = [t for t in profile.tables if t.status == "error"]
        assert len(valid_tables) >= 1
        assert len(error_tables) >= 1
        assert valid_tables[0].source_file == "valid.csv"

    def test_compact_profile_preserves_schema_and_omits_bulky_rows(self, tmp_path):
        biz_dir = tmp_path / "biz_test_compact"
        biz_dir.mkdir()

        readme_text = "Cửa hàng bán sỉ vật liệu xây dựng. Giao hàng trong ngày."
        (biz_dir / "README.md").write_text(readme_text, encoding="utf-8")

        # Create table with huge text in rows and unique values
        huge_val_1 = "A" * 15000
        huge_val_2 = "B" * 15000
        df = pd.DataFrame({
            "ma_hang": ["MH1", "MH2"],
            "mo_ta": [huge_val_1, huge_val_2],
            "ngay": ["2026-08-01", "2026-08-15"],
            "so_luong": [100, 200],
        })
        df.to_csv(biz_dir / "vat_lieu.csv", index=False)

        profile = profile_business_package(biz_dir, "biz_test_compact")
        verbose_md = format_profile_for_prompt(profile, compact=False)
        compact_md = format_profile_for_prompt(profile, compact=True)

        # Verbose contains the huge string representations
        assert len(verbose_md) > 30000
        assert huge_val_1 in verbose_md

        # Compact stays small and omits the bulky cell strings
        assert len(compact_md) < 2000
        assert huge_val_1 not in compact_md

        # But compact strictly preserves schema inventory, README, all columns, and dtypes!
        assert str(biz_dir) not in compact_md
        assert "BUSINESS_DIR" in compact_md
        assert readme_text in compact_md
        assert "vat_lieu.csv" in compact_md
        assert "`ma_hang`" in compact_md
        assert "`mo_ta`" in compact_md
        assert "`ngay`" in compact_md
        assert "`so_luong`" in compact_md
        assert "2026-08-01 .. 2026-08-15" not in compact_md
        assert 'Sample row' not in compact_md
        assert 'categorical' not in compact_md
