"""Sandbox code execution utility for running generated Python code safely.

Pre-imports `vn_norm`, `parse_vn_number`, and `parse_vn_date` so generated code can
reliably handle Vietnamese dates (`"1 thg 6 2025"`), comma-formatted numbers (`"560,000"`),
and Unicode NFC string matching.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

_CODE_BLOCK_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)


@dataclass
class SandboxResult:
    """Result of executing agent-generated Python code."""

    success: bool
    parsed_output: Optional[Dict[str, Any]] = None
    stdout: str = ""
    stderr: str = ""
    error_message: str = ""


def extract_python_code(llm_response: str) -> Optional[str]:
    """Extract the last ```python ... ``` code block from an LLM response."""
    matches = _CODE_BLOCK_RE.findall(llm_response or "")
    if not matches:
        return None
    return matches[-1].strip()


def run_python_in_sandbox(
    code: str,
    business_dir: str,
    calendar_path: str = "",
    work_dir: str = "/tmp/datamate_work",
    timeout_sec: int = 15,
) -> SandboxResult:
    """Execute Python code in a subprocess with `BUSINESS_DIR` and Vietnamese helpers."""
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
            f"BUSINESS_DIR = {os.path.abspath(business_dir)!r}\n"
            f"CALENDAR_PATH = {calendar_path!r}\n\n"
        )
        tmp_file.write(header + code + "\n")

    env = os.environ.copy()
    env["BUSINESS_DIR"] = os.path.abspath(business_dir)
    env["CALENDAR_PATH"] = calendar_path
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = subprocess.run(
            [sys.executable, script_path],
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
            error_message=f"TimeoutError: Code execution exceeded {timeout_sec} seconds.",
        )
    except Exception as exc:
        return SandboxResult(
            success=False,
            error_message=f"SubprocessExecutionError: {exc}",
        )
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if proc.returncode != 0:
        return SandboxResult(
            success=False,
            stdout=stdout,
            stderr=stderr,
            error_message=stderr or f"Process exited with non-zero code {proc.returncode}",
        )

    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return SandboxResult(
            success=False,
            stdout=stdout,
            stderr=stderr,
            error_message="Code executed without error, but printed nothing to stdout.",
        )

    last_line = lines[-1]
    try:
        payload = json.loads(last_line)
        if not isinstance(payload, dict) or "type" not in payload:
            return SandboxResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                error_message=f"Last stdout line is not a JSON dict with 'type': {last_line}",
            )
        return SandboxResult(
            success=True,
            parsed_output=payload,
            stdout=stdout,
            stderr=stderr,
        )
    except json.JSONDecodeError as exc:
        return SandboxResult(
            success=False,
            stdout=stdout,
            stderr=stderr,
            error_message=f"Failed to parse JSON from last stdout line ({last_line!r}): {exc}",
        )
