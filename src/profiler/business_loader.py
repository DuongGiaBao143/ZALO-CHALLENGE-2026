"""Loads and profiles a business data package (.csv, .xlsx, .sqlite, README.md).

Key features:
- Detailed file inventory and per-table status ('ok', 'partial', 'error').
- Safe SQLite inspection in mode=ro with properly escaped/quoted identifiers (_quote_sql_id) and PRAGMA table_info.
- Excel title row inspection with candidate header row detection, raw preview, and uncertainty flags.
- Date range extraction with strict ambiguity guards (never infers US-style dates or uses arbitrary numeric columns).
- Explicit truncation indicators for samples and unique categorical values.
- Graceful error preservation: readable portions are preserved when any file/sheet fails.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import python_calamine  # noqa: F401
    _CALAMINE_AVAILABLE = True
except ImportError:
    _CALAMINE_AVAILABLE = False

from src.schemas import BusinessProfile, TableSchema


def _safe_str(val: Any) -> str:
    """Safely convert a value to string, handling None and NaN."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return ""
    return str(val).strip()


def _quote_sql_id(identifier: str) -> str:
    """Safely quote an SQL identifier (table or column name) by doubling internal double quotes."""
    escaped = str(identifier).replace('"', '""')
    return f'"{escaped}"'


def _detect_excel_header_candidate(
    raw_preview_df: pd.DataFrame,
) -> Tuple[int, bool, List[List[str]]]:
    """Inspect raw rows (header=None) of an Excel sheet to detect candidate header row.

    Returns:
        (candidate_header_idx, header_uncertainty, raw_preview_rows)
    """
    if raw_preview_df.empty:
        return 0, False, []

    preview_rows: List[List[str]] = []
    max_preview_rows = min(5, len(raw_preview_df))
    for i in range(max_preview_rows):
        row_vals = [_safe_str(val) for val in raw_preview_df.iloc[i].tolist()]
        preview_rows.append(row_vals)

    # Check non-empty cell counts and string counts across the first few rows
    num_inspect = min(6, len(raw_preview_df))
    row_stats = []
    for r in range(num_inspect):
        row = raw_preview_df.iloc[r]
        non_empty = [
            v
            for v in row
            if v is not None
            and not (isinstance(v, float) and np.isnan(v))
            and str(v).strip() != ""
        ]
        str_count = sum(
            1
            for v in non_empty
            if isinstance(v, str) and not v.strip().replace(".", "", 1).isdigit()
        )
        row_stats.append((len(non_empty), str_count))

    candidate_idx = 0
    header_uncertainty = False

    if len(row_stats) > 1:
        row0_count, row0_strs = row_stats[0]
        best_candidate = 0
        best_score = row0_strs

        for r_idx in range(1, len(row_stats)):
            cnt, sc = row_stats[r_idx]
            if cnt >= 2 and sc > best_score:
                best_candidate = r_idx
                best_score = sc

        if best_candidate != 0 and (
            row0_count <= 2
            or best_score >= row0_strs + 3
            or (best_score >= 4 and best_score >= row0_strs * 1.5)
        ):
            candidate_idx = best_candidate
            header_uncertainty = True
        elif row0_count <= 1 and any(cnt >= 2 for cnt, _ in row_stats[1:]):
            candidate_idx = 1
            header_uncertainty = True

    return candidate_idx, header_uncertainty, preview_rows


_ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLASH_DATE_REGEX = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _extract_date_ranges(df: pd.DataFrame) -> Optional[Dict[str, str]]:
    """Detect date columns and extract min/max date ranges when reliably observed.

    Guards against:
    - Arbitrary numeric columns (e.g. numeric 'time' or timestamps) are NEVER inferred as dates.
    - Ambiguous numeric date strings (e.g. '01/02/2026') are NOT converted to US-style dates.
    - Ambiguous date formats without clear day > 12 disambiguation are omitted.
    """
    date_ranges: Dict[str, str] = {}

    for col in df.columns:
        # 1. Reject numeric columns immediately (even if named 'time', 'timestamp', etc.)
        if pd.api.types.is_numeric_dtype(df[col]):
            continue

        series = df[col].dropna()
        if series.empty:
            continue

        # 2. If native datetime dtype
        if pd.api.types.is_datetime64_any_dtype(series):
            min_d = series.min()
            max_d = series.max()
            if pd.notna(min_d) and pd.notna(max_d):
                date_ranges[str(col)] = (
                    f"{pd.to_datetime(min_d).strftime('%Y-%m-%d')} .. {pd.to_datetime(max_d).strftime('%Y-%m-%d')}"
                )
            continue

        # 3. String columns: only inspect if column name explicitly denotes a date
        col_lower = str(col).lower()
        if not any(term in col_lower for term in ("ngày", "ngay", "date")):
            continue

        sample_str = [str(x).strip() for x in series.head(50) if str(x).strip()]
        if not sample_str:
            continue

        # Case A: Standard unambiguous ISO YYYY-MM-DD
        if all(_ISO_DATE_REGEX.match(s) for s in sample_str):
            try:
                parsed = pd.to_datetime(series, format="%Y-%m-%d", errors="coerce").dropna()
                if not parsed.empty:
                    min_d = parsed.min().strftime("%Y-%m-%d")
                    max_d = parsed.max().strftime("%Y-%m-%d")
                    date_ranges[str(col)] = f"{min_d} .. {max_d}"
            except Exception:
                pass
            continue

        # Case B: Slash dates DD/MM/YYYY vs MM/DD/YYYY
        # Check if samples match DD/MM/YYYY pattern
        slash_matches = [_SLASH_DATE_REGEX.match(s) for s in sample_str]
        if all(m is not None for m in slash_matches):
            # Check for ambiguity: in DD/MM/YYYY, first part is day. If all first parts <= 12 and second <= 12,
            # it is inherently ambiguous without explicit locale context. Omit rather than produce false coverage!
            has_unambiguous_day = any(int(m.group(1)) > 12 for m in slash_matches if m)
            if has_unambiguous_day:
                try:
                    # Unambiguously Vietnamese DD/MM/YYYY
                    parsed = pd.to_datetime(series, format="%d/%m/%Y", errors="coerce").dropna()
                    if not parsed.empty:
                        min_d = parsed.min().strftime("%Y-%m-%d")
                        max_d = parsed.max().strftime("%Y-%m-%d")
                        date_ranges[str(col)] = f"{min_d} .. {max_d}"
                except Exception:
                    pass
            # If day and month are both <= 12, omit date_range to avoid false US-style coverage.
            continue

    return date_ranges or None


def _extract_df_schema(
    df: pd.DataFrame,
    source_file: str,
    table_name: str,
    max_sample_rows: int = 5,
    max_unique_categorical: int = 25,
    candidate_header_row: Optional[int] = 0,
    header_uncertainty: bool = False,
    raw_preview: Optional[List[List[Any]]] = None,
) -> TableSchema:
    columns = [str(c) for c in df.columns]
    dtypes = {str(col): str(dtype) for col, dtype in df.dtypes.items()}
    row_count = int(len(df))

    sample_df = df.head(max_sample_rows).fillna("")
    sample_rows = sample_df.to_dict(orient="records")
    truncated_rows = row_count > max_sample_rows

    categorical_values: Dict[str, List[str]] = {}
    truncated_categorical = False

    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            non_null = df[col].dropna()
            uniq = non_null.astype(str).unique().tolist()
            if any(len(str(x)) > 80 for x in uniq):
                continue
            if 0 < len(uniq) <= max_unique_categorical:
                categorical_values[str(col)] = uniq
            elif len(uniq) > max_unique_categorical:
                categorical_values[str(col)] = uniq[:max_unique_categorical]
                truncated_categorical = True

    date_range = _extract_date_ranges(df)

    return TableSchema(
        source_file=source_file,
        table_name=table_name,
        columns=columns,
        dtypes=dtypes,
        row_count=row_count,
        sample_rows=sample_rows,
        categorical_values=categorical_values,
        status="ok",
        date_range=date_range,
        candidate_header_row=candidate_header_row,
        header_uncertainty=header_uncertainty,
        raw_preview=raw_preview or [],
        truncated_rows=truncated_rows,
        truncated_categorical=truncated_categorical,
    )


def profile_business_package(
    business_dir: str | Path,
    business_id: str,
    max_sample_rows: int = 5,
    max_unique_categorical: int = 25,
) -> BusinessProfile:
    """Inspect all data files (.csv, .xlsx, .sqlite) and README.md for a business."""
    b_path = Path(business_dir)
    if not b_path.exists():
        return BusinessProfile(
            business_id=business_id,
            business_dir=str(b_path),
            readme_text="",
            error=f"Business directory not found: {b_path}",
        )

    readme_text = ""
    for readme_name in ("README.md", "readme.md", "README.txt", "readme.txt"):
        readme_file = b_path / readme_name
        if readme_file.exists():
            readme_text = readme_file.read_text(encoding="utf-8", errors="replace")
            break

    tables: List[TableSchema] = []
    files_list: List[str] = []
    file_inventory: List[Dict[str, Any]] = []

    for entry in sorted(b_path.iterdir()):
        if not entry.is_file():
            continue

        fname = entry.name
        files_list.append(fname)
        suffix = entry.suffix.lower()
        size_bytes = entry.stat().st_size
        inv_record: Dict[str, Any] = {
            "name": fname,
            "suffix": suffix,
            "size_bytes": size_bytes,
            "status": "ok",
        }

        # Skip readme in table parsing
        if fname.lower().startswith("readme"):
            inv_record["status"] = "doc"
            file_inventory.append(inv_record)
            continue

        try:
            if suffix == ".csv":
                try:
                    df = pd.read_csv(entry, low_memory=False, encoding="utf-8")
                except UnicodeDecodeError:
                    df = pd.read_csv(entry, low_memory=False, encoding="utf-8-sig")

                tables.append(
                    _extract_df_schema(
                        df,
                        source_file=fname,
                        table_name=entry.stem,
                        max_sample_rows=max_sample_rows,
                        max_unique_categorical=max_unique_categorical,
                        candidate_header_row=0,
                        header_uncertainty=False,
                    )
                )

            elif suffix in (".xlsx", ".xls"):
                excel_engine = "calamine" if _CALAMINE_AVAILABLE else None
                xls = pd.ExcelFile(entry, engine=excel_engine)
                for sheet_name in xls.sheet_names:
                    try:
                        raw_preview_df = xls.parse(sheet_name, header=None, nrows=15)
                        candidate_hdr, uncertainty, preview_rows = _detect_excel_header_candidate(
                            raw_preview_df
                        )

                        df = xls.parse(sheet_name, header=candidate_hdr)
                        tables.append(
                            _extract_df_schema(
                                df,
                                source_file=fname,
                                table_name=str(sheet_name),
                                max_sample_rows=max_sample_rows,
                                max_unique_categorical=max_unique_categorical,
                                candidate_header_row=candidate_hdr,
                                header_uncertainty=uncertainty,
                                raw_preview=preview_rows,
                            )
                        )
                    except Exception as sheet_exc:
                        tables.append(
                            TableSchema(
                                source_file=fname,
                                table_name=str(sheet_name),
                                columns=[],
                                dtypes={},
                                row_count=0,
                                status="error",
                                error_message=f"Error reading sheet {sheet_name}: {sheet_exc}",
                            )
                        )

            elif suffix in (".sqlite", ".db", ".sqlite3"):
                # Safe read-only SQLite inspection with doubled-quote identifiers
                conn_uri = f"file:{entry.resolve().as_posix()}?mode=ro"
                conn = sqlite3.connect(conn_uri, uri=True)
                try:
                    cursor = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
                    )
                    table_names = [row[0] for row in cursor.fetchall()]

                    for tname in table_names:
                        try:
                            t_quoted = _quote_sql_id(tname)
                            # Safe row count
                            count_cur = conn.execute(f"SELECT COUNT(*) FROM {t_quoted}")
                            row_cnt = int(count_cur.fetchone()[0])

                            # Column inspection via PRAGMA
                            pragma_cur = conn.execute(f"PRAGMA table_info({t_quoted})")
                            pragma_cols = pragma_cur.fetchall()
                            cols = [row[1] for row in pragma_cols]
                            col_types = {row[1]: str(row[2]) for row in pragma_cols}

                            # Sample rows query
                            df_sample = pd.read_sql_query(
                                f"SELECT * FROM {t_quoted} LIMIT {max_sample_rows}", conn
                            )
                            dtypes = {
                                str(c): col_types.get(c, str(df_sample[c].dtype if c in df_sample else "object"))
                                for c in cols
                            }
                            sample_rows = df_sample.fillna("").to_dict(orient="records")

                            # Categorical unique preview with truncation detection
                            cat_vals: Dict[str, List[str]] = {}
                            truncated_cat = False

                            if row_cnt <= 10000:
                                for col in cols:
                                    c_type = col_types.get(col, "").upper()
                                    if "INT" in c_type or "REAL" in c_type or "FLOAT" in c_type:
                                        continue
                                    try:
                                        c_quoted = _quote_sql_id(col)
                                        uniq_cur = conn.execute(
                                            f"SELECT DISTINCT {c_quoted} FROM {t_quoted} WHERE {c_quoted} IS NOT NULL LIMIT {max_unique_categorical + 1}"
                                        )
                                        u_vals = [str(r[0]) for r in uniq_cur.fetchall()]
                                        if len(u_vals) > max_unique_categorical:
                                            cat_vals[col] = u_vals[:max_unique_categorical]
                                            truncated_cat = True
                                        elif 0 < len(u_vals) <= max_unique_categorical:
                                            cat_vals[col] = u_vals
                                    except Exception:
                                        pass

                            tables.append(
                                TableSchema(
                                    source_file=fname,
                                    table_name=tname,
                                    columns=cols,
                                    dtypes=dtypes,
                                    row_count=row_cnt,
                                    sample_rows=sample_rows,
                                    categorical_values=cat_vals,
                                    status="ok",
                                    truncated_rows=row_cnt > max_sample_rows,
                                    truncated_categorical=truncated_cat,
                                )
                            )
                        except Exception as tbl_exc:
                            tables.append(
                                TableSchema(
                                    source_file=fname,
                                    table_name=tname,
                                    columns=[],
                                    dtypes={},
                                    row_count=0,
                                    status="error",
                                    error_message=f"Error inspecting table {tname}: {tbl_exc}",
                                )
                            )
                finally:
                    conn.close()

            else:
                inv_record["status"] = "unsupported_extension"

        except Exception as exc:
            inv_record["status"] = "error"
            tables.append(
                TableSchema(
                    source_file=fname,
                    table_name=f"ERROR_{fname}",
                    columns=[],
                    dtypes={},
                    row_count=0,
                    status="error",
                    error_message=str(exc),
                )
            )

        file_inventory.append(inv_record)

    return BusinessProfile(
        business_id=business_id,
        business_dir=os.path.abspath(str(b_path)),
        readme_text=readme_text,
        tables=tables,
        files=files_list,
        file_inventory=file_inventory,
    )


def format_profile_for_prompt(profile: BusinessProfile, compact: bool = False) -> str:
    """Format a BusinessProfile into a structured Markdown section for the LLM prompt.

    Args:
        profile: The extracted BusinessProfile.
        compact: When True, includes only the folder, README, file/sheet inventory,
                 all columns/dtypes, read errors and required Excel header hints.
                 Defaults to False for detailed diagnostic profiling.
    """
    if compact:
        lines = ["BUSINESS_DIR: biến đường dẫn do môi trường thực thi cấp; dùng trực tiếp, không gán đường dẫn tuyệt đối.",
                 "Files: " + ", ".join(profile.files),
                 "README:\n" + profile.readme_text.strip(), "Schema:"]
        groups = {}
        for table in profile.tables:
            columns = tuple((c, table.dtypes.get(c, 'unknown')) for c in table.columns)
            header = table.candidate_header_row if table.header_uncertainty else None
            key = (table.source_file, columns, header, table.status, table.error_message)
            groups.setdefault(key, []).append(table.table_name)
        for (filename, columns, header, status, error), sheets in groups.items():
            lines.append(f"{filename} / sheets: {', '.join(sheets)}")
            if status != 'ok' or error:
                lines.append(f"status={status}; error={error or ''}")
            if header is not None:
                lines.append(f"Excel header={header} (candidate; verify if needed)")
            if columns:
                lines.append(", ".join(f"`{column}`: {dtype}" for column, dtype in columns))
        return "\n".join(lines)

    lines = [
        f"### Business ID: `{profile.business_id}`",
        "- Thư mục dữ liệu: Truy cập trực tiếp qua biến `BUSINESS_DIR` đã cấu hình sẵn trong môi trường (không hardcode đường dẫn tuyệt đối).",
        f"- Danh sách file ({len(profile.files)} files): {', '.join(f'`{f}`' for f in profile.files)}",
    ]

    if profile.readme_text:
        lines.extend(
            [
                "",
                "#### Business README.md (Ghi chú nghiệp vụ riêng của quán):",
                profile.readme_text.strip(),
            ]
        )

    lines.extend(["", "#### Tables & Sheets Schema:"])
    lines.append(
        "> Thông tin dưới đây là mẫu trích xuất. Code cần đọc toàn bộ dữ liệu liên quan từ BUSINESS_DIR; "
        "không kết luận thiếu dữ liệu chỉ từ mẫu."
    )

    seen_file_cols: Dict[str, Dict[Tuple[str, ...], str]] = {}

    for t in profile.tables:
        lines.append(
            f"\n##### File: `{t.source_file}` | Table/Sheet: `{t.table_name}` (Status: `{t.status}`)"
        )
        if t.status == "error":
            lines.append(f"- ❌ Lỗi đọc bảng: `{t.error_message}`")
            continue

        lines.append(f"- Tổng số dòng (`row_count`): {t.row_count}")

        if t.header_uncertainty:
            lines.append(
                f"- ⚠️ **Cảnh báo header**: Sheet này có thể chứa dòng tiêu đề biểu mẫu phía trên. "
                f"Candidate header index = {t.candidate_header_row}. "
                f"Khi dùng `pandas.read_excel`, cân nhắc truyền `header={t.candidate_header_row}`."
            )
            if t.raw_preview:
                lines.append("  - Xem trước các dòng đầu (raw preview):")
                for r_idx, r_vals in enumerate(t.raw_preview):
                    lines.append(f"    * Row {r_idx}: {r_vals}")

        # Deduplicate schema across multi-sheet files with identical columns
        file_key = t.source_file
        cols_sig = tuple(t.columns)
        if file_key in seen_file_cols and cols_sig in seen_file_cols[file_key]:
            first_sheet = seen_file_cols[file_key][cols_sig]
            lines.append(f"- Cấu trúc cột & dtypes: Giống hệt sheet `{first_sheet}` ở trên.")
            if t.date_range:
                lines.append("- Observed date ranges:")
                for dcol, drange in t.date_range.items():
                    lines.append(f"  * `{dcol}`: {drange}")
            continue

        if file_key not in seen_file_cols:
            seen_file_cols[file_key] = {}
        seen_file_cols[file_key][cols_sig] = t.table_name

        col_specs = [f"`{c}` ({t.dtypes.get(c, 'unknown')})" for c in t.columns]
        lines.append("- Columns: " + (", ".join(col_specs) if col_specs else "(None)"))

        if t.date_range:
            lines.append("- Observed date ranges:")
            for dcol, drange in t.date_range.items():
                lines.append(f"  * `{dcol}`: {drange}")

        # Provide bounded categorical values (status/enums only in compact mode)
        if t.categorical_values:
            trunc_note = " (truncated)" if t.truncated_categorical else ""
            lines.append(f"- Unique categorical values sample{trunc_note}:")
            for col, vals in t.categorical_values.items():
                lines.append(f"  * `{col}`: {vals}")

        if t.sample_rows:
            trunc_note = f" (first {len(t.sample_rows)} rows)" if t.truncated_rows else ""
            lines.append(f"- Sample rows{trunc_note}:")
            for r in t.sample_rows:
                lines.append(f"  `{r}`")

    return "\n".join(lines)
