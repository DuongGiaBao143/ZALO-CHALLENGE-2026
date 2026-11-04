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

from src.postprocess.normalizer import (
    format_number_value,
    format_percent_value,
)
from src.schemas import AnswerType, ProtocolKind, VALID_ANSWER_TYPES

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
    try:
        res = _orig_to_datetime(arg, *args, **kwargs)
        if isinstance(res, pd.Series) and res.isna().all() and len(res) > 0 and not pd.isna(arg).all():
            return parse_vn_date(arg)
        return res
    except Exception:
        return parse_vn_date(arg)

pd.to_datetime = _patched_to_datetime

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
            cwd=str(work_path),
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
