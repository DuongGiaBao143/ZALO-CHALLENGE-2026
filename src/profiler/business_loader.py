"""Loads and profiles a business data package (.csv, .xlsx, .sqlite, README.md)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from src.schemas import BusinessProfile, TableSchema


def _extract_df_schema(
    df: pd.DataFrame,
    source_file: str,
    table_name: str,
    max_sample_rows: int = 5,
    max_unique_categorical: int = 25,
) -> TableSchema:
    columns = [str(c) for c in df.columns]
    dtypes = {str(col): str(dtype) for col, dtype in df.dtypes.items()}
    row_count = int(len(df))

    sample_df = df.head(max_sample_rows).fillna("")
    sample_rows = sample_df.to_dict(orient="records")

    categorical_values: Dict[str, List[str]] = {}
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            uniq = df[col].dropna().astype(str).unique().tolist()
            if 0 < len(uniq) <= max_unique_categorical:
                categorical_values[str(col)] = uniq[:max_unique_categorical]

    return TableSchema(
        source_file=source_file,
        table_name=table_name,
        columns=columns,
        dtypes=dtypes,
        row_count=row_count,
        sample_rows=sample_rows,
        categorical_values=categorical_values,
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
    for readme_name in ("README.md", "readme.md", "README.txt"):
        readme_file = b_path / readme_name
        if readme_file.exists():
            readme_text = readme_file.read_text(encoding="utf-8", errors="replace")
            break

    tables: List[TableSchema] = []
    files_list: List[str] = []

    for entry in sorted(b_path.iterdir()):
        if not entry.is_file():
            continue
        files_list.append(entry.name)
        suffix = entry.suffix.lower()

        try:
            if suffix == ".csv":
                df = pd.read_csv(entry, low_memory=False)
                tables.append(
                    _extract_df_schema(
                        df,
                        source_file=entry.name,
                        table_name=entry.stem,
                        max_sample_rows=max_sample_rows,
                        max_unique_categorical=max_unique_categorical,
                    )
                )
            elif suffix in (".xlsx", ".xls"):
                xls = pd.ExcelFile(entry)
                for sheet_name in xls.sheet_names:
                    df = xls.parse(sheet_name)
                    tables.append(
                        _extract_df_schema(
                            df,
                            source_file=entry.name,
                            table_name=str(sheet_name),
                            max_sample_rows=max_sample_rows,
                            max_unique_categorical=max_unique_categorical,
                        )
                    )
            elif suffix in (".sqlite", ".db", ".sqlite3"):
                conn = sqlite3.connect(f"file:{entry.as_posix()}?mode=ro", uri=True)
                try:
                    cursor = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
                    )
                    table_names = [row[0] for row in cursor.fetchall()]
                    for tname in table_names:
                        df = pd.read_sql_query(f'SELECT * FROM "{tname}"', conn)
                        tables.append(
                            _extract_df_schema(
                                df,
                                source_file=entry.name,
                                table_name=tname,
                                max_sample_rows=max_sample_rows,
                                max_unique_categorical=max_unique_categorical,
                            )
                        )
                finally:
                    conn.close()
        except Exception as exc:
            tables.append(
                TableSchema(
                    source_file=entry.name,
                    table_name=f"ERROR_READING_{entry.name}",
                    columns=[],
                    dtypes={"error": str(exc)},
                    row_count=0,
                )
            )

    return BusinessProfile(
        business_id=business_id,
        business_dir=os.path.abspath(str(b_path)),
        readme_text=readme_text,
        tables=tables,
        files=files_list,
    )


def format_profile_for_prompt(profile: BusinessProfile) -> str:
    """Format a BusinessProfile into a structured Markdown section for the LLM prompt."""
    lines = [
        f"### Business ID: `{profile.business_id}`",
        f"- Directory path (`BUSINESS_DIR`): `{profile.business_dir}`",
        f"- Files available: `{profile.files}`",
    ]
    if profile.readme_text:
        lines.extend(["", "#### Business README.md:", profile.readme_text.strip()])

    lines.extend(["", "#### Tables / Sheets Schema:"])
    for t in profile.tables:
        lines.append(
            f"\n##### File: `{t.source_file}` | Table/Sheet: `{t.table_name}` (Rows: {t.row_count})"
        )
        col_specs = [f"`{c}` ({t.dtypes.get(c, 'unknown')})" for c in t.columns]
        lines.append("- Columns: " + ", ".join(col_specs))
        if t.categorical_values:
            lines.append("- Categorical unique values:")
            for col, vals in t.categorical_values.items():
                lines.append(f"  * `{col}`: {vals}")
        if t.sample_rows:
            lines.append(f"- Sample rows (first {len(t.sample_rows)}):")
            for r in t.sample_rows:
                lines.append(f"  `{r}`")

    return "\n".join(lines)
