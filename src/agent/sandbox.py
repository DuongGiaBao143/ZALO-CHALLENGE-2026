"""Bounded process runner and JSON execution protocol for agent-generated Python code.

SECURITY NOTICE:
Subprocess execution timeout and working-directory containment DO NOT constitute an OS-level
security sandbox or container boundary. In production and evaluation, host security
relies strictly on Docker container boundaries:
  - Network disabled (--network none)
  - Data directory mounted strictly read-only (/data:ro)
  - Execution confined to isolated temporary work directories (/tmp/datamate_work)
Subprocess execution here provides bounded execution limits (timeout_sec) and structured
diagnostic feedback (stdout/stderr/returncode) to support agentic self-repair.

STRICT JSON PROTOCOL SPECIFICATION:
Generated scripts must communicate with the host by emitting a single JSON object on the
LAST non-empty line of stdout. Stale or earlier candidates are never resurrected.
Supported protocol messages:

1. Discovery / Observation (Exploration turn):
   {
     "kind": "observation",
     "data": <bounded summary, list of columns, counts, or sample dict>,
     "message": "<short string description of observation>"
   }

2. Final Candidate Answer:
   {
     "kind": "final",
     "type": "number" | "percent" | "string" | "date" | "boolean" | "list" | "table" | "unanswerable" | "abstain",
     "answer": <candidate value or null>,
     "evidence": "<non-empty string trace of computation or data source>",
     "reason": "<required non-empty string reasoning for unanswerable, recommended for abstain>"
   }
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import unicodedata
import numpy as np
import pandas as pd

from src.postprocess.normalizer import (
    format_number_value,
    format_percent_value,
)
from src.schemas import AnswerType, ProtocolKind, VALID_ANSWER_TYPES


def strip_accents(s: Any) -> str:
    """Strip accents and lower case for robust column name matching."""
    text = str(s).replace('đ', 'd').replace('Đ', 'D')
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if unicodedata.category(c) != 'Mn')


def unmerge_and_ffill(
    df: pd.DataFrame,
    ffill_cols: Optional[List[str]] = None,
    id_col: Optional[str] = None
) -> pd.DataFrame:
    """Propagate parent-level attributes down to child item rows in grouped/merged tabular data.
    
    Complies strictly with Rulebook Section 8:
    'Ô để trống ở các dòng sau của cùng một nhóm dòng: giống ô đó ở dòng đầu nhóm: 
    khách, ghi chú, trạng thái của đơn áp cho mọi dòng của đơn.'
    """
    if not isinstance(df, pd.DataFrame) or len(df) == 0:
        return df

    df = df.copy()
    cols = list(df.columns)

    norm_col_map = {c: strip_accents(c).replace('_', ' ').replace('-', ' ').strip() for c in cols}

    detected_id = None
    if id_col and id_col in df.columns:
        detected_id = id_col
    else:
        for c, norm_c in norm_col_map.items():
            if any(k in norm_c for k in [
                'ma don', 'ma chung tu', 'ma phieu', 'ma hoa don',
                'so chung tu', 'so hoa don', 'order id', 'invoice id'
            ]):
                detected_id = c
                break

    # 1. If explicit columns are provided, forward-fill those columns directly
    if ffill_cols:
        target_cols = [c for c in ffill_cols if c in df.columns]
        if target_cols:
            if detected_id and df[detected_id].notna().any():
                order_group = df[detected_id].notna().cumsum()
                df[target_cols] = df.groupby(order_group)[target_cols].ffill()
            else:
                df[target_cols] = df[target_cols].ffill()
        return df

    # 2. Automatic parent-column detection:
    if detected_id and df[detected_id].isna().any():
        child_mask = df[detected_id].isna()
        parent_keywords = [
            'ma', 'code', 'id', 'ngay', 'date', 'time', 'thoi gian',
            'trang thai', 'status', 'khach', 'customer', 'nhan vien',
            'creator', 'thu ngan', 'ghi chu', 'note', 'hinh thuc'
        ]
        cols_to_fill = [detected_id]
        for c, norm_c in norm_col_map.items():
            if c == detected_id:
                continue
            is_parent_name = any(k in norm_c for k in parent_keywords)
            null_on_child = df.loc[child_mask, c].isna().mean() if child_mask.any() else 0
            null_on_parent = df.loc[~child_mask, c].isna().mean() if (~child_mask).any() else 1
            if is_parent_name or (null_on_child > 0.8 and null_on_parent < 0.2):
                cols_to_fill.append(c)

        order_group = df[detected_id].notna().cumsum()
        df[cols_to_fill] = df.groupby(order_group)[cols_to_fill].ffill()
    elif not detected_id:
        # Fallback for generic parent columns if no explicit ID column
        parent_keywords = ['ma don', 'ngay dat', 'ngay lap', 'trang thai', 'ten khach']
        generic_cols = [
            c for c, norm_c in norm_col_map.items()
            if any(k in norm_c for k in parent_keywords) and df[c].isna().any()
        ]
        if generic_cols:
            df[generic_cols] = df[generic_cols].ffill()

    return df


def unmerge_openpyxl_sheet(ws: Any) -> None:
    """Unmerge all merged ranges in an openpyxl worksheet and replicate top-left cell values."""
    if not hasattr(ws, 'merged_cells'):
        return
    for rng in list(ws.merged_cells.ranges):
        min_col, min_row, max_col, max_row = rng.min_col, rng.min_row, rng.max_col, rng.max_row
        top_val = ws.cell(min_row, min_col).value
        ws.unmerge_cells(start_row=min_row, start_column=min_col, end_row=max_row, end_column=max_col)
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                ws.cell(r, c).value = top_val


def load_excel_unmerge(
    io: Any,
    sheet_name: Any = 0,
    header: Any = 0,
    ffill_cols: Optional[List[str]] = None,
    id_col: Optional[str] = None,
    **kwargs
) -> Any:
    """Load Excel sheet(s) and forward-fill merged/grouped parent columns."""
    res = pd.read_excel(io, sheet_name=sheet_name, header=header, **kwargs)
    if isinstance(res, pd.DataFrame):
        return unmerge_and_ffill(res, ffill_cols=ffill_cols, id_col=id_col)
    elif isinstance(res, dict):
        return {s: unmerge_and_ffill(df, ffill_cols=ffill_cols, id_col=id_col) for s, df in res.items()}
    return res

_CODE_BLOCK_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_THINK_BLOCK_RE = re.compile(r"(?:<think>.*?</think>|<\|thought\|>.*?(?:<\|/thought\|>|<channel\|>))", re.DOTALL | re.IGNORECASE)
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)

MAX_DIAGNOSTIC_CHARS = 2500
MAX_OUTPUT_CAPTURE_CHARS = 50000
MAX_OBSERVATION_DATA_CHARS = 4000
MAX_OBSERVATION_MESSAGE_CHARS = 1000


@dataclass
class SandboxResult:
    """Detailed result of executing agent-generated Python code."""

    success: bool
    kind: str = ProtocolKind.ERROR.value  # "observation", "final", "error"
    parsed_output: Optional[Dict[str, Any]] = None
    stdout: str = ""
    stderr: str = ""
    returncode: Optional[int] = None
    timeout: bool = False
    error_kind: Optional[str] = None  # "timeout", "runtime_error", "protocol_violation", "validation_error"
    error_message: str = ""


def extract_python_code(llm_response: str) -> Optional[str]:
    """Extract the last ```python ... ``` code block from an LLM response (ignoring <think> blocks first)."""
    if not llm_response:
        return None
    cleaned = _THINK_BLOCK_RE.sub("", llm_response)
    matches = _CODE_BLOCK_RE.findall(cleaned)
    if not matches:
        matches = _CODE_BLOCK_RE.findall(llm_response)
    if not matches:
        return None
    return matches[-1].strip()


def _check_finite_values(obj: Any) -> None:
    """Recursively check that an object contains no NaN or Inf floats."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError(f"Non-finite float value encountered: {obj}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _check_finite_values(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _check_finite_values(item)


def _parse_strict_json(json_str: str) -> Any:
    """Parse JSON while strictly rejecting NaN, Infinity, -Infinity constants."""
    def _reject_constant(c: str) -> None:
        raise ValueError(f"Non-finite JSON constant not allowed: {c!r}")

    return json.loads(json_str, parse_constant=_reject_constant)


def _validate_calendar_date(val: Any) -> str:
    """Validate calendar date semantics for YYYY-MM-DD or YYYY-MM."""
    if not isinstance(val, str):
        raise ValueError(f"Date answer must be a string, got {type(val).__name__}")
    s = val.strip()

    # Full date YYYY-MM-DD
    m_day = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m_day:
        try:
            parsed = datetime.strptime(s, "%Y-%m-%d")
            if parsed.strftime("%Y-%m-%d") != s:
                raise ValueError
            return s
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid calendar date: {s!r}") from exc

    # Month only YYYY-MM
    m_month = re.match(r"^(\d{4})-(\d{2})$", s)
    if m_month:
        try:
            parsed = datetime.strptime(s, "%Y-%m")
            if parsed.strftime("%Y-%m") != s:
                raise ValueError
            return s
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid calendar month: {s!r}") from exc

    raise ValueError(f"Date answer must match ISO format YYYY-MM-DD or YYYY-MM, got: {s!r}")


def validate_protocol_payload(payload: Any) -> Tuple[str, Dict[str, Any]]:
    """Validate and classify a parsed stdout payload according to the strict JSON protocol.

    Enforces:
    - Must be a JSON dict with required 'kind' ('observation' or 'final').
    - Strict value types, actual calendar date validity, rectangular table shapes.
    - No nested dicts/lists inside list items.
    - Non-empty evidence string for all final answers.
    - Non-empty reason string for unanswerable.
    - Observation message must be a bounded string.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"Protocol payload must be a JSON object (dict), got {type(payload).__name__}.")

    _check_finite_values(payload)

    if "kind" not in payload:
        raise ValueError("Missing required 'kind' field in protocol payload. Must be 'observation' or 'final'.")

    kind = str(payload["kind"]).strip().lower()
    if kind in ("unanswerable", "abstain"):
        payload["type"] = kind
        payload["kind"] = "final"
        kind = "final"

    if kind == ProtocolKind.OBSERVATION.value:
        data = payload.get("data")
        msg = payload.get("message")

        if msg is not None:
            if not isinstance(msg, str):
                raise ValueError(f"Observation message must be a string, got {type(msg).__name__}.")
            if len(msg) > MAX_OBSERVATION_MESSAGE_CHARS:
                payload["message"] = msg[:MAX_OBSERVATION_MESSAGE_CHARS] + "... [truncated]"

        if data is None and not msg:
            raise ValueError("Observation payload must include 'data' or 'message'.")

        # Bound observation data representation if too large
        data_str = json.dumps(data, ensure_ascii=False) if data is not None else ""
        if len(data_str) > MAX_OBSERVATION_DATA_CHARS:
            payload["data_truncated"] = True
            payload["data"] = data_str[:MAX_OBSERVATION_DATA_CHARS] + "... [truncated]"

        return ProtocolKind.OBSERVATION.value, payload

    elif kind == ProtocolKind.FINAL.value:
        if "type" not in payload:
            raise ValueError("Final answer payload missing required 'type' field.")

        ans_type = str(payload["type"]).strip().lower()
        if ans_type not in VALID_ANSWER_TYPES:
            raise ValueError(
                f"Invalid answer type {ans_type!r}. Allowed types: {sorted(VALID_ANSWER_TYPES)}"
            )

        # Evidence is required for all final answers
        evidence = payload.get("evidence")
        if not evidence or not isinstance(evidence, str) or not evidence.strip():
            if ans_type == AnswerType.ABSTAIN.value:
                evidence = payload.get("reason") or "Abstained by agent"
                payload["evidence"] = evidence
            else:
                raise ValueError("Missing or empty 'evidence' string in final payload.")

        raw_answer = payload.get("answer")

        # Type-specific shape & value validations
        if ans_type == AnswerType.UNANSWERABLE.value:
            reason = payload.get("reason")
            if not reason or not isinstance(reason, str) or not reason.strip():
                raise ValueError("Final 'unanswerable' type requires a non-empty 'reason' string.")
            payload["answer"] = None

        elif ans_type == AnswerType.ABSTAIN.value:
            payload["answer"] = None

        elif ans_type == AnswerType.STRING.value:
            if not isinstance(raw_answer, str) or not raw_answer.strip():
                raise ValueError(
                    f"String answer must be a non-empty string, got {type(raw_answer).__name__}: {raw_answer!r}"
                )
            if raw_answer.strip().lower() in ("không rõ", "khong ro", "không xác định", "không biết", "n/a", "unknown", "none", "null"):
                raise ValueError(
                    f"Uncertain placeholder string {raw_answer!r} is not a valid entity answer; use type='abstain' or 'unanswerable' or 'boolean'."
                )

        elif ans_type == AnswerType.DATE.value:
            payload["answer"] = _validate_calendar_date(raw_answer)

        elif ans_type in (AnswerType.NUMBER.value, AnswerType.PERCENT.value):
            if raw_answer is None or isinstance(raw_answer, bool) or isinstance(raw_answer, (dict, list)):
                raise ValueError(f"Numeric answer for type {ans_type!r} cannot be {type(raw_answer).__name__}.")
            if ans_type == AnswerType.NUMBER.value:
                payload["answer"] = format_number_value(raw_answer)
            else:
                payload["answer"] = format_percent_value(raw_answer)

        elif ans_type == AnswerType.BOOLEAN.value:
            if isinstance(raw_answer, bool):
                payload["answer"] = raw_answer
            elif isinstance(raw_answer, str) and raw_answer.lower() in ("true", "1", "đúng"):
                payload["answer"] = True
            elif isinstance(raw_answer, str) and raw_answer.lower() in ("false", "0", "sai"):
                payload["answer"] = False
            else:
                raise ValueError(f"Invalid boolean answer: {raw_answer!r}")

        elif ans_type == AnswerType.LIST.value:
            if not isinstance(raw_answer, list):
                raise ValueError("List answer must be a JSON array (list).")
            # Disallow nested dicts or lists in list items
            for item in raw_answer:
                if isinstance(item, (dict, list)):
                    raise ValueError(
                        f"List elements must be strings or numbers, found nested {type(item).__name__}."
                    )
                if isinstance(item, float) and (math.isnan(item) or math.isinf(item)):
                    raise ValueError("List elements must be finite values.")

        elif ans_type == AnswerType.TABLE.value:
            if not isinstance(raw_answer, dict):
                raise ValueError("Table answer must be a dict with 'columns' and 'rows'.")
            cols = raw_answer.get("columns")
            rows = raw_answer.get("rows")
            if not isinstance(cols, list) or not isinstance(rows, list):
                raise ValueError("Table answer must contain list of 'columns' and list of 'rows'.")

            # Auto-convert list of dicts to list of lists if needed
            if rows and isinstance(rows[0], dict):
                rows = [[r.get(c) for c in cols] for r in rows]
                raw_answer["rows"] = rows

            num_cols = len(cols)
            # Enforce rectangular table shape: no ragged rows allowed
            for r_idx, r in enumerate(rows):
                if not isinstance(r, (list, tuple)):
                    raise ValueError(f"Table row {r_idx} must be a list, got {type(r).__name__}.")
                if len(r) != num_cols:
                    raise ValueError(
                        f"Ragged table row at index {r_idx}: expected {num_cols} columns, got {len(r)}."
                    )
                for cell in r:
                    if isinstance(cell, (dict, list)):
                        raise ValueError(
                            f"Table cells cannot be nested dicts/lists, got {type(cell).__name__} in row {r_idx}."
                        )
                    if isinstance(cell, float) and (math.isnan(cell) or math.isinf(cell)):
                        raise ValueError(f"Table cells must be finite values in row {r_idx}.")

        return ProtocolKind.FINAL.value, payload

    else:
        raise ValueError(
            f"Unsupported protocol kind: {kind!r}. Expected 'observation' or 'final'."
        )


_SANDBOX_RUNTIME_HELPERS = """
import datetime as _dt
import re as _re

class _SmartPathStr(str):
    def __truediv__(self, other):
        return _SmartPathStr(os.path.join(self, str(other).lstrip('/\\\\')))
    def __rtruediv__(self, other):
        return _SmartPathStr(os.path.join(str(other), self.lstrip('/\\\\')))

BUSINESS_DIR = _SmartPathStr(BUSINESS_DIR)
CALENDAR_PATH = _SmartPathStr(CALENDAR_PATH)
RULEBOOK_PATH = _SmartPathStr(RULEBOOK_PATH)

_orig_dumps = json.dumps
def _sanitize_obs_nan(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, dict):
        return {str(k): _sanitize_obs_nan(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize_obs_nan(item) for item in v]
    return v

def _default_json_enc(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (pd.Timestamp, _dt.datetime, _dt.date)):
        if pd.isna(x):
            return None
        return x.isoformat()[:10] if hasattr(x, 'isoformat') else str(x)
    if isinstance(x, (np.ndarray, pd.Series, pd.Index)):
        return x.tolist()
    if isinstance(x, pd.DataFrame):
        return _sanitize_obs_nan(x.head(20).to_dict(orient='records'))
    if hasattr(x, 'item'):
        return x.item()
    return str(x)

def _patched_dumps(obj, *args, **kwargs):
    kwargs.pop('indent', None)
    if isinstance(obj, dict):
        k_str = str(obj.get('kind', '')).strip().lower()
        if k_str == 'final':
            ans_t = str(obj.get('type', '')).strip().lower()
            ans_v = obj.get('answer')
            if ans_t in ('number', 'percent') and isinstance(ans_v, list):
                obj = dict(obj)
                obj['type'] = 'list'
        elif k_str == 'observation':
            obj = _sanitize_obs_nan(dict(obj))
    if 'default' not in kwargs:
        kwargs['default'] = _default_json_enc
    return _orig_dumps(obj, *args, **kwargs)

json.dumps = _patched_dumps

_orig_to_datetime = pd.to_datetime
def _patched_to_datetime(arg, *args, **kwargs):
    kwargs.setdefault('errors', 'coerce')
    try:
        res = _orig_to_datetime(arg, *args, **kwargs)
        if isinstance(res, pd.Series) and res.isna().all() and len(res) > 0 and not pd.isna(arg).all():
            return parse_vn_date(arg)
        return res
    except Exception:
        return parse_vn_date(arg)

pd.to_datetime = _patched_to_datetime

def _smart_resolve_file(path_or_str):
    if not isinstance(path_or_str, (str, Path)):
        return path_or_str
    p = str(path_or_str)
    if os.path.exists(p):
        return p
    base = os.path.basename(p)
    direct = os.path.join(BUSINESS_DIR, base)
    if os.path.exists(direct):
        return direct
    try:
        mojibake = base.encode('utf-8').decode('cp437', errors='ignore')
        m_path = os.path.join(BUSINESS_DIR, mojibake)
        if os.path.exists(m_path):
            return m_path
    except Exception:
        pass
    try:
        mojibake2 = base.encode('cp437', errors='ignore').decode('utf-8', errors='ignore')
        m2_path = os.path.join(BUSINESS_DIR, mojibake2)
        if os.path.exists(m2_path):
            return m2_path
    except Exception:
        pass
    ext = os.path.splitext(base)[1].lower()
    clean_target = ''.join(c.lower() for c in base if c.isalnum())
    if clean_target and os.path.exists(BUSINESS_DIR):
        for cand in os.listdir(BUSINESS_DIR):
            if os.path.splitext(cand)[1].lower() == ext:
                clean_cand = ''.join(c.lower() for c in cand if c.isalnum())
                if clean_target in clean_cand or clean_cand in clean_target:
                    return os.path.join(BUSINESS_DIR, cand)
    return p

def _detect_best_header(df):
    if not isinstance(df, pd.DataFrame) or len(df) == 0:
        return df
    cols = [str(c) for c in df.columns]
    unnamed_cnt = sum(1 for c in cols if c.startswith('Unnamed:') or c == 'nan' or not c.strip())
    if unnamed_cnt / max(1, len(cols)) < 0.4:
        return df
    for r_idx in range(min(10, len(df))):
        row_vals = df.iloc[r_idx].values
        str_vals = [str(v).strip() for v in row_vals if pd.notna(v) and str(v).strip() != '' and str(v) != 'nan']
        if len(str_vals) >= max(3, len(cols) * 0.5):
            non_num = [v for v in str_vals if not v.replace('.', '', 1).replace(',', '', 1).replace('-', '', 1).isdigit()]
            if len(non_num) >= len(str_vals) * 0.7:
                new_cols = [str(v).strip() if pd.notna(v) and str(v).strip() != '' else f'col_{i}' for i, v in enumerate(row_vals)]
                new_df = df.iloc[r_idx + 1:].copy()
                new_df.columns = new_cols
                new_df.reset_index(drop=True, inplace=True)
                return new_df
    return df

_orig_read_csv = pd.read_csv
def _smart_read_csv(filepath_or_buffer, *args, **kwargs):
    if isinstance(filepath_or_buffer, (str, Path)):
        filepath_or_buffer = _smart_resolve_file(filepath_or_buffer)
    hdr_specified = ('header' in kwargs and kwargs['header'] is not None and kwargs['header'] != 0)
    res = _orig_read_csv(filepath_or_buffer, *args, **kwargs)
    if not hdr_specified and isinstance(res, pd.DataFrame):
        res = _detect_best_header(res)
    return res
pd.read_csv = _smart_read_csv

def strip_accents(s):
    text = str(s).replace('đ', 'd').replace('Đ', 'D')
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if unicodedata.category(c) != 'Mn')

def unmerge_and_ffill(df, ffill_cols=None, id_col=None):
    if not isinstance(df, pd.DataFrame) or len(df) == 0:
        return df
    df = df.copy()
    cols = list(df.columns)
    norm_col_map = {c: strip_accents(c).replace('_', ' ').replace('-', ' ').strip() for c in cols}
    detected_id = None
    if id_col and id_col in df.columns:
        detected_id = id_col
    else:
        for c, norm_c in norm_col_map.items():
            if any(k in norm_c for k in ['ma don', 'ma chung tu', 'ma phieu', 'ma hoa don', 'so chung tu', 'so hoa don', 'order id', 'invoice id']):
                detected_id = c
                break
    if ffill_cols:
        target_cols = [c for c in ffill_cols if c in df.columns]
        if target_cols:
            if detected_id and df[detected_id].notna().any():
                order_group = df[detected_id].notna().cumsum()
                df[target_cols] = df.groupby(order_group)[target_cols].ffill()
            else:
                df[target_cols] = df[target_cols].ffill()
        return df
    if detected_id and df[detected_id].isna().any():
        child_mask = df[detected_id].isna()
        parent_keywords = ['ma', 'code', 'id', 'ngay', 'date', 'time', 'thoi gian', 'trang thai', 'status', 'khach', 'customer', 'nhan vien', 'creator', 'thu ngan', 'ghi chu', 'note', 'hinh thuc']
        cols_to_fill = [detected_id]
        for c, norm_c in norm_col_map.items():
            if c == detected_id:
                continue
            is_parent_name = any(k in norm_c for k in parent_keywords)
            null_on_child = df.loc[child_mask, c].isna().mean() if child_mask.any() else 0
            null_on_parent = df.loc[~child_mask, c].isna().mean() if (~child_mask).any() else 1
            if is_parent_name or (null_on_child > 0.8 and null_on_parent < 0.2):
                cols_to_fill.append(c)
        order_group = df[detected_id].notna().cumsum()
        df[cols_to_fill] = df.groupby(order_group)[cols_to_fill].ffill()
    elif not detected_id:
        parent_keywords = ['ma don', 'ngay dat', 'ngay lap', 'trang thai', 'ten khach']
        generic_cols = [c for c, norm_c in norm_col_map.items() if any(k in norm_c for k in parent_keywords) and df[c].isna().any()]
        if generic_cols:
            df[generic_cols] = df[generic_cols].ffill()
    return df

def unmerge_openpyxl_sheet(ws):
    if not hasattr(ws, 'merged_cells'):
        return
    for rng in list(ws.merged_cells.ranges):
        min_col, min_row, max_col, max_row = rng.min_col, rng.min_row, rng.max_col, rng.max_row
        top_val = ws.cell(min_row, min_col).value
        ws.unmerge_cells(start_row=min_row, start_column=min_col, end_row=max_row, end_column=max_col)
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                ws.cell(r, c).value = top_val

def load_excel_unmerge(io, sheet_name=0, header=0, ffill_cols=None, id_col=None, **kwargs):
    res = pd.read_excel(io, sheet_name=sheet_name, header=header, **kwargs)
    if isinstance(res, pd.DataFrame):
        return unmerge_and_ffill(res, ffill_cols=ffill_cols, id_col=id_col)
    elif isinstance(res, dict):
        return {s: unmerge_and_ffill(df, ffill_cols=ffill_cols, id_col=id_col) for s, df in res.items()}
    return res

_orig_read_excel = pd.read_excel
def _smart_read_excel(io, *args, **kwargs):
    unmerge_flag = kwargs.pop('unmerge', None)
    if isinstance(io, (str, Path)):
        io = _smart_resolve_file(io)
    sheet = kwargs.get('sheet_name')
    hdr_specified = ('header' in kwargs and kwargs['header'] is not None and kwargs['header'] != 0)
    try:
        res = _orig_read_excel(io, *args, **kwargs)
        if not hdr_specified:
            if isinstance(res, pd.DataFrame):
                res = _detect_best_header(res)
            elif isinstance(res, dict):
                res = {k: _detect_best_header(v) for k, v in res.items()}
        if unmerge_flag or unmerge_flag is None:
            if isinstance(res, pd.DataFrame):
                res = unmerge_and_ffill(res)
            elif isinstance(res, dict):
                res = {k: unmerge_and_ffill(v) for k, v in res.items()}
        return res
    except (ValueError, KeyError, FileNotFoundError):
        if sheet and isinstance(sheet, str):
            for fname in os.listdir(BUSINESS_DIR):
                if fname.lower().endswith(('.xlsx', '.xls')) and fname != os.path.basename(str(io)):
                    other_path = os.path.join(BUSINESS_DIR, fname)
                    try:
                        other_xls = pd.ExcelFile(other_path)
                        if sheet in other_xls.sheet_names:
                            res = _orig_read_excel(other_path, *args, **kwargs)
                            if not hdr_specified and isinstance(res, pd.DataFrame):
                                res = _detect_best_header(res)
                            if unmerge_flag or unmerge_flag is None:
                                if isinstance(res, pd.DataFrame):
                                    res = unmerge_and_ffill(res)
                                elif isinstance(res, dict):
                                    res = {k: unmerge_and_ffill(v) for k, v in res.items()}
                            return res
                    except Exception:
                        pass
        raise
pd.read_excel = _smart_read_excel

_orig_excel_file = pd.ExcelFile
class _SmartExcelFile(_orig_excel_file):
    def __init__(self, path_or_buffer, *args, **kwargs):
        if isinstance(path_or_buffer, (str, Path)):
            path_or_buffer = _smart_resolve_file(path_or_buffer)
        super().__init__(path_or_buffer, *args, **kwargs)
pd.ExcelFile = _SmartExcelFile

_orig_sqlite_connect = sqlite3.connect
def _smart_sqlite_connect(database, *args, **kwargs):
    if isinstance(database, (str, Path)):
        database = _smart_resolve_file(database)
    return _orig_sqlite_connect(database, *args, **kwargs)
sqlite3.connect = _smart_sqlite_connect

_orig_open = open
def _smart_open(file, *args, **kwargs):
    if isinstance(file, (str, Path)):
        file = _smart_resolve_file(file)
    return _orig_open(file, *args, **kwargs)
import builtins
builtins.open = _smart_open

_DATE_STR_PAT = _re.compile(
    r'^\\s*(?:\\d{4}-\\d{1,2}-\\d{1,2}|\\d{1,2}[/-]\\d{1,2}[/-]\\d{2,4}|\\d{1,2}\\s*(?:thg|tháng|thang)\\s*\\d{1,2}(?:\\s*(?:năm|nam|,)?\\s*\\d{4})?)(?:\\s+\\d{1,2}:\\d{2}(?::\\d{2})?)?\\s*$',
    _re.IGNORECASE
)

def _is_date_scalar(other):
    if isinstance(other, (pd.Timestamp, _dt.datetime, _dt.date, np.datetime64)):
        return True
    if isinstance(other, str) and _DATE_STR_PAT.match(other):
        return True
    return False

def _coerce_other_date(other):
    if isinstance(other, str):
        return parse_vn_date(other)
    if isinstance(other, _dt.date) and not isinstance(other, _dt.datetime):
        return pd.Timestamp(other)
    return other

def _make_series_cmp(orig_op, op_name):
    def _wrapper(self, other):
        if self.dtype == object:
            if _is_date_scalar(other):
                try:
                    coerced_self = parse_vn_date(self)
                    if coerced_self.notna().any():
                        coerced_other = _coerce_other_date(other)
                        return orig_op(coerced_self, coerced_other)
                except Exception:
                    pass
            elif op_name in ('__lt__', '__le__', '__gt__', '__ge__') and isinstance(other, (int, float, np.number)) and not isinstance(other, (bool, np.bool_)):
                try:
                    coerced_num = parse_vn_number(self)
                    if coerced_num.notna().any():
                        return orig_op(coerced_num, other)
                except Exception:
                    pass
        return orig_op(self, other)
    return _wrapper

for _op_name in ('__lt__', '__le__', '__gt__', '__ge__', '__eq__', '__ne__'):
    setattr(pd.Series, _op_name, _make_series_cmp(getattr(pd.Series, _op_name), _op_name))

_orig_series_sum = pd.Series.sum
def _patched_series_sum(self, *args, **kwargs):
    if self.dtype == object:
        try:
            num_s = parse_vn_number(self)
            if num_s.notna().any():
                return _orig_series_sum(num_s, *args, **kwargs)
        except Exception:
            pass
    return _orig_series_sum(self, *args, **kwargs)
pd.Series.sum = _patched_series_sum

_orig_series_mean = pd.Series.mean
def _patched_series_mean(self, *args, **kwargs):
    if self.dtype == object:
        try:
            num_s = parse_vn_number(self)
            if num_s.notna().any():
                return _orig_series_mean(num_s, *args, **kwargs)
        except Exception:
            pass
    return _orig_series_mean(self, *args, **kwargs)
pd.Series.mean = _patched_series_mean

_orig_series_astype = pd.Series.astype
def _patched_series_astype(self, dtype, *args, **kwargs):
    try:
        return _orig_series_astype(self, dtype, *args, **kwargs)
    except (ValueError, TypeError):
        if self.dtype == object and dtype in (float, int, 'float', 'float64', 'int', 'int64', np.float64, np.int64):
            num_s = parse_vn_number(self)
            if dtype in (int, 'int', 'int64', np.int64):
                return _orig_series_astype(num_s.fillna(0), dtype, *args, **kwargs)
            return _orig_series_astype(num_s, dtype, *args, **kwargs)
        raise
pd.Series.astype = _patched_series_astype

_orig_dt_desc = pd.Series.__dict__['dt']
class _SmartDtAccessor:
    def __get__(self, instance, owner=None):
        if instance is None:
            return _orig_dt_desc.__get__(None, owner)
        try:
            return _orig_dt_desc.__get__(instance, owner)
        except AttributeError:
            return _orig_dt_desc.__get__(parse_vn_date(instance), owner)
pd.Series.dt = _SmartDtAccessor()

try:
    from pandas.core.groupby.generic import SeriesGroupBy as _SGB
    _orig_sgb_sum = _SGB.sum
    def _patched_sgb_sum(self, *args, **kwargs):
        try:
            obj_s = getattr(self, 'obj', None)
            if isinstance(obj_s, pd.Series) and obj_s.dtype == object:
                num_s = parse_vn_number(obj_s)
                if num_s.notna().any():
                    self.obj = num_s
        except Exception:
            pass
        return _orig_sgb_sum(self, *args, **kwargs)
    _SGB.sum = _patched_sgb_sum
except Exception:
    pass
"""


def run_python_in_sandbox(
    code: str,
    business_dir: str,
    calendar_path: str = "",
    work_dir: str = "/tmp/datamate_work",
    timeout_sec: int = 15,
    as_of_date: str = "",
    rulebook_path: str = "",
) -> SandboxResult:
    """Execute Python code in a bounded subprocess and validate JSON protocol on LAST line only.

    Enforces:
    - Only the LAST non-empty line of stdout is evaluated. Earlier candidates are not resurrected.
    - Preserves stdout, stderr, returncode, timeout diagnostics with bounded feedback.
    - Rejects unformatted stdout, syntax/runtime errors, and protocol violations.
    """
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        dir=str(work_path),
        encoding="utf-8",
        delete=False,
    ) as tmp_file:
        script_path = tmp_file.name
        header = (
            "import os, sys, json, math, sqlite3, unicodedata, warnings\n"
            f"sys.path.insert(0, {PROJECT_ROOT!r})\n"
            "from pathlib import Path\n"
            "null = None; true = True; false = False\n"
            "import pandas as pd\n"
            "import numpy as np\n"
            "from src.postprocess.vn_utils import vn_norm, parse_vn_number, parse_vn_date\n"
            "warnings.filterwarnings('ignore')\n"
            "try:\n"
            "    import python_calamine\n"
            "except ImportError:\n"
            "    pass\n"
            "else:\n"
            "    pd.set_option('io.excel.xlsx.reader', 'calamine')\n"
            f"BUSINESS_DIR = {os.path.abspath(business_dir)!r}\n"
            f"try:\n"
            f"    os.chdir(BUSINESS_DIR)\n"
            f"except Exception:\n"
            f"    pass\n"
            f"CALENDAR_PATH = {calendar_path!r}\n\n"
            f"AS_OF_DATE = {as_of_date!r}\n"
            f"RULEBOOK_PATH = {rulebook_path!r}\n"
            f"{_SANDBOX_RUNTIME_HELPERS}\n"
        )
        tmp_file.write(header + code + "\n")

    env = os.environ.copy()
    for secret_name in ('WANDB_API_KEY', 'HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN'):
        env.pop(secret_name, None)
    env['WANDB_MODE'] = 'disabled'
    env["BUSINESS_DIR"] = os.path.abspath(business_dir)
    env["CALENDAR_PATH"] = calendar_path
    env["AS_OF_DATE"] = as_of_date
    env["RULEBOOK_PATH"] = rulebook_path
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Each candidate already has its own process; avoid nested CPU thread pools.
    for thread_var in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        env[thread_var] = '1'

    try:
        proc = subprocess.run(
            [sys.executable, "-B", script_path],
            cwd=str(os.path.abspath(business_dir)) if os.path.exists(business_dir) else str(work_path),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(
            success=False,
            kind=ProtocolKind.ERROR.value,
            timeout=True,
            error_kind="timeout",
            error_message=f"TimeoutError: Code execution exceeded {timeout_sec} seconds timeout.",
        )
    except Exception as exc:
        return SandboxResult(
            success=False,
            kind=ProtocolKind.ERROR.value,
            error_kind="execution_error",
            error_message=f"SubprocessExecutionError: {exc}",
        )
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass

    raw_stdout = (proc.stdout or "").strip()
    raw_stderr = (proc.stderr or "").strip()
    retcode = proc.returncode

    # Bound stored output capture
    stdout = raw_stdout[:MAX_OUTPUT_CAPTURE_CHARS]
    stderr = raw_stderr[:MAX_OUTPUT_CAPTURE_CHARS]

    # If subprocess crashed with non-zero exit code
    if retcode != 0:
        bounded_err = stderr[-MAX_DIAGNOSTIC_CHARS:] if len(stderr) > MAX_DIAGNOSTIC_CHARS else stderr
        return SandboxResult(
            success=False,
            kind=ProtocolKind.ERROR.value,
            stdout=stdout,
            stderr=stderr,
            returncode=retcode,
            error_kind="runtime_error",
            error_message=bounded_err or f"Process exited with non-zero code {retcode}",
        )

    # Subprocess exited 0: Inspect ONLY the LAST non-empty line of stdout
    lines = [line.strip() for line in raw_stdout.splitlines() if line.strip()]
    if not lines:
        return SandboxResult(
            success=False,
            kind=ProtocolKind.ERROR.value,
            stdout=stdout,
            stderr=stderr,
            returncode=retcode,
            error_kind="protocol_violation",
            error_message="Script exited with code 0 but produced no output on stdout.",
        )

    last_line = lines[-1]

    # Parse last line with strict JSON parser
    try:
        raw_payload = _parse_strict_json(last_line)
    except Exception as parse_exc:
        bounded_line = last_line[:MAX_DIAGNOSTIC_CHARS]
        return SandboxResult(
            success=False,
            kind=ProtocolKind.ERROR.value,
            stdout=stdout,
            stderr=stderr,
            returncode=retcode,
            error_kind="protocol_violation",
            error_message=(
                f"Protocol violation: Last non-empty line of stdout is not valid strict JSON: {parse_exc}\n"
                f"Line content: {bounded_line!r}"
            ),
        )

    # Validate against protocol schema
    try:
        kind, validated_payload = validate_protocol_payload(raw_payload)
        return SandboxResult(
            success=True,
            kind=kind,
            parsed_output=validated_payload,
            stdout=stdout,
            stderr=stderr,
            returncode=retcode,
        )
    except ValueError as val_err:
        return SandboxResult(
            success=False,
            kind=ProtocolKind.ERROR.value,
            stdout=stdout,
            stderr=stderr,
            returncode=retcode,
            error_kind="protocol_violation",
            error_message=f"Protocol validation error on final stdout line: {val_err}",
        )
