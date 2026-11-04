"""Independent Codex checks, separate from Antigravity's tests."""
import sqlite3

from src.profiler.business_loader import profile_business_package


def test_sqlite_identifier_with_quote_remains_readable(tmp_path):
    with sqlite3.connect(tmp_path / "orders.sqlite") as conn:
        conn.execute('CREATE TABLE "sales""archive" ("customer""name" TEXT, qty INTEGER)')
        conn.execute('INSERT INTO "sales""archive" VALUES (?, ?)', ("Lan", 2))
    profile = profile_business_package(tmp_path, "shop")
    table = next(t for t in profile.tables if t.table_name == 'sales"archive')
    assert table.status == "ok", table.error_message
    assert table.row_count == 1
    assert table.columns == ['customer"name', "qty"]


def test_sqlite_unique_preview_reports_its_truncation(tmp_path):
    with sqlite3.connect(tmp_path / "orders.sqlite") as conn:
        conn.execute("CREATE TABLE orders (customer TEXT)")
        conn.executemany("INSERT INTO orders VALUES (?)", [(f"Customer{i}",) for i in range(30)])
    profile = profile_business_package(tmp_path, "shop", max_unique_categorical=5)
    table = profile.tables[0]
    assert len(table.categorical_values["customer"]) == 5
    assert table.truncated_categorical, "Omitted unique values must be marked as truncated."


def test_ambiguous_numeric_dates_never_become_false_coverage(tmp_path):
    (tmp_path / "sales.csv").write_text("ngay,amount\n01/02/2026,1\n02/02/2026,2\n", encoding="utf-8")
    table = profile_business_package(tmp_path, "shop").tables[0]
    # An uncertain date range may be omitted; an inferred US-style Jan 2 start
    # must not silently masquerade as verified coverage for a Vietnamese date column.
    observed = str(table.date_range or {})
    assert "2026-01-02" not in observed, observed
