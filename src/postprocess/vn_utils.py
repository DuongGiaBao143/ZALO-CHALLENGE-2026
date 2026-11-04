"""Vietnamese data cleaning utilities for messy tabular data (.csv, .xlsx, .sqlite).

Handles the real-world traps discovered in `train` and `public_test`:
  1. Numbers stored as strings with comma thousands separators (e.g., `"560,000"`).
  2. Mixed Vietnamese date formats in the same column (e.g., `"1 thg 6 2025"`, `"01/06/2025"`,
     `"2025-06-01"`, or dates missing the year where the year comes from the Excel sheet name).
  3. Unicode NFC vs NFD mismatches when filtering Vietnamese product/customer names.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from datetime import date, datetime, timedelta
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


@functools.lru_cache(maxsize=32768)
def _vn_norm_cached(val: str) -> str:
    return normalize_string(val)


def vn_norm(val: Any) -> Any:
    """Normalize a single string or a pandas Series of strings using DataMate NFC rules."""
    if isinstance(val, pd.Series):
        s_col = val.fillna("").astype(str)
        unique_vals = s_col.unique()
        norm_map = {u: _vn_norm_cached(u) for u in unique_vals}
        return s_col.map(norm_map)
    if isinstance(val, str):
        return _vn_norm_cached(val)
    return normalize_string(val)


@functools.lru_cache(maxsize=32768)
def _parse_vn_number_str_cached(s: str) -> Any:
    s = s.strip()
    if not s or s.lower() in ("nan", "none", "null", "nat", ""):
        return np.nan
    s = re.sub(r"(?i)\s*(vnđ|vnd|đ)\s*$", "", s).strip()

    # Case: "1tr090" -> 1 million + 90 thousand = 1090000
    m_trm = re.match(r"^(\d+)\s*(?:tr|trieu|triệu)\s*(\d+)$", s, re.IGNORECASE)
    if m_trm:
        tr_part = int(m_trm.group(1)) * 1_000_000
        rem_str = m_trm.group(2)
        if len(rem_str) == 3:
            rem = int(rem_str) * 1_000
        elif len(rem_str) == 1:
            rem = int(rem_str) * 100_000
        elif len(rem_str) == 2:
            rem = int(rem_str) * 10_000
        else:
            rem = int(rem_str)
        return tr_part + rem

    # Case: "1,19tr" or "1.19tr"
    m_tr = re.match(r"^([\d.,]+)\s*(?:tr|trieu|triệu)$", s, re.IGNORECASE)
    if m_tr:
        num_str = m_tr.group(1).replace(",", ".")
        try:
            return float(num_str) * 1_000_000
        except ValueError:
            pass

    # Case: "45k"
    m_k = re.match(r"^([\d.,]+)\s*k$", s, re.IGNORECASE)
    if m_k:
        num_str = m_k.group(1).replace(",", ".")
        try:
            return float(num_str) * 1_000
        except ValueError:
            pass

    # Vietnamese dot thousands separator (e.g. "99.000" or "12.500.000")
    if re.match(r"^\d{1,3}(\.\d{3})+(,\d+)?$", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.match(r"^\d{1,3}(,\d{3})+(\.\d+)?$", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", "")

    try:
        num = float(s)
        return int(num) if num.is_integer() else num
    except ValueError:
        return np.nan


def parse_vn_number(val: Any) -> Any:
    """Convert Vietnamese formatted number strings (e.g. `'560,000'`, `'99.000đ'`, `'1,19tr'`, `'1tr090'`, `'45k'`) to float/int.

    Works on both scalar values and `pd.Series`. Optimized with LRU caching and unique-value mapping.
    """
    if isinstance(val, pd.Series):
        if pd.api.types.is_numeric_dtype(val):
            return val
        unique_vals = val.dropna().unique()
        if len(unique_vals) == 0:
            return pd.Series([np.nan] * len(val), index=val.index, dtype=float)
        num_map = {u: parse_vn_number(u) for u in unique_vals}
        return val.map(num_map)

    if val is None or (isinstance(val, float) and np.isnan(val)):
        return np.nan
    if isinstance(val, (int, float, np.number)) and not isinstance(val, (bool, np.bool_)):
        return int(val) if float(val).is_integer() else float(val)
    return _parse_vn_number_str_cached(str(val))


def _normalize_single_vn_date_str(text: Any, default_year: Optional[int] = None) -> Optional[str]:
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return None

    # Handle Excel serial dates as integer / float (e.g. 45658)
    if isinstance(text, (int, float, np.number)) and not isinstance(text, (bool, np.bool_)):
        try:
            val_int = int(text)
            if 30000 <= val_int <= 60000:
                origin = datetime(1899, 12, 30)
                return (origin + timedelta(days=val_int)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    s = str(text).strip()
    if not s or s.lower() in ("nan", "none", "nat", ""):
        return None

    # Handle Excel serial dates as string (e.g. "45658" or "45658.0")
    m_serial = re.match(r"^(\d{5})(?:\.0+)?$", s)
    if m_serial:
        serial_int = int(m_serial.group(1))
        if 30000 <= serial_int <= 60000:
            origin = datetime(1899, 12, 30)
            return (origin + timedelta(days=serial_int)).strftime("%Y-%m-%d")

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


@functools.lru_cache(maxsize=16384)
def _parse_hashable_vn_date(val: Any, default_year: Optional[int] = None) -> Any:
    norm_str = _normalize_single_vn_date_str(val, default_year=default_year)
    if norm_str is None:
        return pd.NaT
    try:
        return pd.Timestamp(norm_str)
    except Exception:
        return pd.to_datetime(norm_str, errors="coerce")


def parse_vn_date(val: Any, default_year: Optional[int] = None) -> Any:
    """Parse mixed Vietnamese date formats (`'1 thg 6 2025'`, `'01/06/2025'`, `'2025-06-01'`).

    Can be called on a `pd.Series` or a single value. Returns `pd.Series` of `datetime64[ns]`
    or a `pd.Timestamp`. Optimized with unique-value mapping for Series and LRU cache for `.apply()`.
    """
    if isinstance(val, pd.Series):
        if pd.api.types.is_datetime64_any_dtype(val):
            return val
        unique_vals = val.dropna().unique()
        if len(unique_vals) == 0:
            return pd.to_datetime(pd.Series([pd.NaT] * len(val), index=val.index))
        dt_map = {}
        for u in unique_vals:
            try:
                dt_map[u] = _parse_hashable_vn_date(u, default_year)
            except TypeError:
                norm_s = _normalize_single_vn_date_str(u, default_year=default_year)
                dt_map[u] = pd.to_datetime(norm_s, errors="coerce") if norm_s is not None else pd.NaT
        return pd.to_datetime(val.map(dt_map), errors="coerce")

    if isinstance(val, pd.Timestamp):
        return val
    if isinstance(val, (datetime, date)):
        return pd.Timestamp(val)
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return pd.NaT
    try:
        return _parse_hashable_vn_date(val, default_year)
    except TypeError:
        norm_str = _normalize_single_vn_date_str(val, default_year=default_year)
        return pd.to_datetime(norm_str, errors="coerce") if norm_str is not None else pd.NaT
