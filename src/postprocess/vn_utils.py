"""Vietnamese data cleaning utilities for messy tabular data (.csv, .xlsx, .sqlite).

Handles the real-world traps discovered in `train` and `public_test`:
  1. Numbers stored as strings with comma thousands separators (e.g., `"560,000"`).
  2. Mixed Vietnamese date formats in the same column (e.g., `"1 thg 6 2025"`, `"01/06/2025"`,
     `"2025-06-01"`, or dates missing the year where the year comes from the Excel sheet name).
  3. Unicode NFC vs NFD mismatches when filtering Vietnamese product/customer names.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.postprocess.normalizer import normalize_string

_VN_THG_FULL_RE = re.compile(
    r"^\s*(\d{1,2})\s*(?:thg|tháng|thang)\s*(\d{1,2})(?:\s*(?:năm|nam|,)?\s*(\d{4}))?(.*)$",
    re.IGNORECASE,
)
_DMY_SLASH_RE = re.compile(
    r"^\s*(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?(.*)$"
)
_ISO_PREFIX_RE = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})(.*)$")


def vn_norm(val: Any) -> Any:
    """Normalize a single string or a pandas Series of strings using DataMate NFC rules."""
    if isinstance(val, pd.Series):
        return val.fillna("").astype(str).map(normalize_string)
    return normalize_string(val)


def parse_vn_number(val: Any) -> Any:
    """Convert Vietnamese formatted number strings (e.g. `'560,000'`, `'12,500.5đ'`) to float/int.

    Works on both scalar values and `pd.Series`.
    """
    if isinstance(val, pd.Series):
        if pd.api.types.is_numeric_dtype(val):
            return val
        cleaned = (
            val.astype(str)
            .str.strip()
            .str.replace(",", "", regex=False)
            .str.replace("đ", "", case=False, regex=False)
            .str.replace("vnd", "", case=False, regex=False)
            .str.strip()
        )
        return pd.to_numeric(cleaned, errors="coerce")

    if val is None or (isinstance(val, float) and np.isnan(val)):
        return np.nan
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return val
    s = str(val).strip().replace(",", "")
    s = re.sub(r"(?i)(vnđ|vnd|đ)$", "", s).strip()
    try:
        num = float(s)
        return int(num) if num.is_integer() else num
    except ValueError:
        return np.nan


def _normalize_single_vn_date_str(text: Any, default_year: Optional[int] = None) -> Optional[str]:
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return None
    s = str(text).strip()
    if not s or s.lower() in ("nan", "none", "nat", ""):
        return None

    # 1. Already ISO YYYY-MM-DD (with optional time suffix)
    m_iso = _ISO_PREFIX_RE.match(s)
    if m_iso:
        y, m, d, rest = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)), m_iso.group(4)
        return f"{y:04d}-{m:02d}-{d:02d}{rest}"

    # 2. Vietnamese "1 thg 6 2025" or "15 tháng 8"
    m_thg = _VN_THG_FULL_RE.match(s)
    if m_thg:
        d = int(m_thg.group(1))
        m = int(m_thg.group(2))
        y_str = m_thg.group(3)
        rest = m_thg.group(4) or ""
        y = int(y_str) if y_str else default_year
        if y is not None:
            return f"{y:04d}-{m:02d}-{d:02d}{rest}"

    # 3. DD/MM/YYYY or DD/MM (Rulebook §8: missing year uses sheet year)
    m_dmy = _DMY_SLASH_RE.match(s)
    if m_dmy:
        d = int(m_dmy.group(1))
        m = int(m_dmy.group(2))
        y_str = m_dmy.group(3)
        rest = m_dmy.group(4) or ""
        if y_str:
            y = int(y_str)
            if y < 100:
                y += 2000
        else:
            y = default_year
        if y is not None and 1 <= m <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{m:02d}-{d:02d}{rest}"

    return s


def parse_vn_date(val: Any, default_year: Optional[int] = None) -> Any:
    """Parse mixed Vietnamese date formats (`'1 thg 6 2025'`, `'01/06/2025'`, `'2025-06-01'`).

    Can be called on a `pd.Series` or a single value. Returns `pd.Series` of `datetime64[ns]`
    or a `pd.Timestamp`.
    """
    if isinstance(val, pd.Series):
        if pd.api.types.is_datetime64_any_dtype(val):
            return val
        normalized = val.map(lambda x: _normalize_single_vn_date_str(x, default_year=default_year))
        return pd.to_datetime(normalized, errors="coerce")

    norm_str = _normalize_single_vn_date_str(val, default_year=default_year)
    return pd.to_datetime(norm_str, errors="coerce")
