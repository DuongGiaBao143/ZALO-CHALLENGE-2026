"""Independent automated tests for P1: Business Loader & Schema Profiler.

Covers:
- Full RAM scanning without 200-row limits
- Separation of exhaustive labels (<=20 unique) vs annotated samples (>20 unique)
- Context capping budget (MAX_SCHEMA_CHARS = 7000)
- Identical sheet deduplication & grouping
- PII column value exclusion
- Real BTC training shops verification (biz_101, biz_111, biz_127) in strictly read-only mode
"""

import os
import sqlite3
import pandas as pd
import pytest

from src.profiler.business_loader import (
    MAX_EXHAUSTIVE_CARDINALITY,
    MAX_SCHEMA_CHARS,
    format_eval_schema,
    profile_business_package,
)
from src.schemas import TableSchema


def test_full_ram_scan_without_200_row_limit(tmp_path):
    """Verify categorical profiling scans entire dataset in RAM without 200-row truncation."""
    # Create 1,000 rows where rare label 'returned' only appears at row 950
    statuses = ["completed"] * 950 + ["returned"] * 50
    df = pd.DataFrame({
        "order_id": [f"DH_{i}" for i in range(1000)],
        "status": statuses,
        "amount": [10000] * 1000,
    })
    csv_path = tmp_path / "orders.csv"
    df.to_csv(csv_path, index=False)

    profile = profile_business_package(tmp_path, "test_shop", metadata_only=True)
    assert len(profile.tables) == 1
    table = profile.tables[0]

    assert "status" in table.categorical_values
    status_vals = table.categorical_values["status"]
    # 'returned' must be captured even though it appears past row 200
    assert "returned" in status_vals
    assert "completed" in status_vals
    assert table.column_unique_counts["status"] == 2
    assert "status" in table.exhaustive_columns


def test_exhaustive_labels_vs_sample_separation():
    """Verify low cardinality produces [TOÀN BỘ NHÃN...] and high cardinality produces [MẪU THAM KHẢO...]."""
    # Low cardinality: 4 unique values
    low_card_vals = ["Chờ duyệt", "Đang giao", "Hoàn thành", "Đã huỷ"]
    # High cardinality: 30 unique values
    high_card_vals = [f"KH_{i}" for i in range(5)]  # Top 5 sample

    table = TableSchema(
        source_file="test.csv",
        table_name="orders",
        columns=["trang_thai", "ma_kh"],
        dtypes={"trang_thai": "object", "ma_kh": "object"},
        row_count=1000,
        categorical_values={
            "trang_thai": low_card_vals,
            "ma_kh": high_card_vals,
        },
        column_unique_counts={"trang_thai": 4, "ma_kh": 85},
        exhaustive_columns=["trang_thai"],
    )

    schema_md = format_eval_schema([table])
    assert "[TOÀN BỘ NHÃN / ALL LABELS (unique=4)] 'trang_thai'" in schema_md
    assert "Chờ duyệt" in schema_md
    assert "[MẪU THAM KHẢO / SAMPLE VALUES (top tần suất, unique=85)] 'ma_kh'" in schema_md


def test_pii_columns_excluded_from_samples(tmp_path):
    """Verify customer PII columns (name, phone, cccd) do not have values dumped in schema."""
    df = pd.DataFrame({
        "ma_don": ["D1", "D2", "D3"],
        "Tên khách hàng": ["Nguyễn Văn A", "Trần Thị B", "Lê Văn C"],
        "Khách hàng": ["Khách 1", "Khách 2", "Khách 3"],
        "Khách": ["A", "B", "C"],
        "Name": ["John Doe", "Jane Doe", "Bob"],
        "SĐT": ["0912345678", "0987654321", "0900000000"],
        "trang_thai": ["Xong", "Huy", "Xong"],
    })
    df.to_csv(tmp_path / "orders.csv", index=False)

    profile = profile_business_package(tmp_path, "shop", metadata_only=True)
    table = profile.tables[0]

    # Columns remain in table schema
    assert "Tên khách hàng" in table.columns
    assert "Khách hàng" in table.columns
    assert "Khách" in table.columns
    assert "Name" in table.columns
    assert "SĐT" in table.columns
    # But values are excluded from categorical_values
    assert "Tên khách hàng" not in table.categorical_values
    assert "Khách hàng" not in table.categorical_values
    assert "Khách" not in table.categorical_values
    assert "Name" not in table.categorical_values
    assert "SĐT" not in table.categorical_values
    assert "trang_thai" in table.categorical_values

    schema_md = format_eval_schema(profile.tables)
    assert "Nguyễn Văn A" not in schema_md
    assert "John Doe" not in schema_md
    assert "0912345678" not in schema_md


def test_context_capping_budget():
    """Verify that schema block strictly respects MAX_SCHEMA_CHARS (<= 7000 chars)."""
    tables = []
    for i in range(25):
        t = TableSchema(
            source_file=f"file_{i}.xlsx",
            table_name=f"Sheet_{i}",
            columns=[f"col_{j}" for j in range(30)],
            dtypes={f"col_{j}": "object" for j in range(30)},
            row_count=5000,
            categorical_values={f"col_{j}": [f"long_sample_value_string_{j}_{k}" for k in range(5)] for j in range(30)},
            column_unique_counts={f"col_{j}": 500 for j in range(30)},
            exhaustive_columns=[],
        )
        tables.append(t)

    schema_md = format_eval_schema(tables)
    assert len(schema_md) <= MAX_SCHEMA_CHARS, f"Schema exceeded {MAX_SCHEMA_CHARS}: len={len(schema_md)}"


def test_identical_sheet_grouping():
    """Verify that multiple sheets with identical schema are consolidated."""
    tables = [
        TableSchema(
            source_file="DonHang.xlsx",
            table_name=f"T{m:02d}-2025",
            columns=["ma_don", "ngay", "tien"],
            dtypes={"ma_don": "object", "ngay": "object", "tien": "int64"},
            row_count=100,
            categorical_values={},
        )
        for m in range(1, 13)
    ]

    schema_md = format_eval_schema(tables)
    assert "12 sheets cùng cấu trúc" in schema_md
    # Shouldn't list all 12 sheets repeatedly on separate lines
    assert schema_md.count("Cột: 'ma_don', 'ngay', 'tien'") == 1


def test_real_training_data_status_labels_detected():
    """Verify real data in data/train/data is scanned correctly in read-only mode."""
    # biz_101: column 'Kết quả' with label 'Xong'
    biz_101_dir = "data/train/data/biz_101"
    if os.path.exists(biz_101_dir):
        p101 = profile_business_package(biz_101_dir, "biz_101", metadata_only=True)
        bh = next(t for t in p101.tables if t.table_name == "ban_hang")
        assert "Kết quả" in bh.categorical_values
        assert "Xong" in bh.categorical_values["Kết quả"]

    # biz_111: table 'don_hang' column 'Xử lý' with 'completed'
    biz_111_dir = "data/train/data/biz_111"
    if os.path.exists(biz_111_dir):
        p111 = profile_business_package(biz_111_dir, "biz_111", metadata_only=True)
        dh = next(t for t in p111.tables if t.table_name == "don_hang")
        assert "Xử lý" in dh.categorical_values
        assert "completed" in dh.categorical_values["Xử lý"]

    # biz_127: table 'don_hang' column 'Tình trạng' with 4 labels
    biz_127_dir = "data/train/data/biz_127"
    if os.path.exists(biz_127_dir):
        p127 = profile_business_package(biz_127_dir, "biz_127", metadata_only=True)
        dh27 = next(t for t in p127.tables if t.table_name == "don_hang")
        assert "Tình trạng" in dh27.categorical_values
        assert "completed" in dh27.categorical_values["Tình trạng"]
        assert "returned" in dh27.categorical_values["Tình trạng"]


def test_exhaustive_25_labels_not_truncated_to_20(tmp_path):
    """Verify columns with 21..25 unique values profiled at max_unique_categorical=25 are not clipped at 20."""
    labels_22 = [f"NHAN_{i:02d}" for i in range(22)]
    pd.DataFrame({"status": labels_22, "val": range(22)}).to_csv(tmp_path / "t.csv", index=False)
    profile = profile_business_package(tmp_path, "shop_22", max_unique_categorical=25, metadata_only=True)
    schema_md = format_eval_schema(profile.tables)
    assert "[TOÀN BỘ NHÃN / ALL LABELS (unique=22)] 'status'" in schema_md
    assert "NHAN_21" in schema_md
