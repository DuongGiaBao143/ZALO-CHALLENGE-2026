"""Unit tests for DataMate CLI scripts (run_inference, evaluate_local, verify_submission)."""

import json
import os
import subprocess
import sys
from pathlib import Path
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def synthetic_cli_data(tmp_path):
    """Setup a miniature data split for CLI testing."""
    data_dir = tmp_path / "cli_data"
    data_dir.mkdir()

    # Rulebook & calendar
    (data_dir / "rulebook.md").write_text("# Rules\nRevenue = sum of line amounts.", encoding="utf-8")
    (data_dir / "calendar.csv").write_text("solar_date,lunar_date\n2026-08-27,2026-07-15\n", encoding="utf-8")

    # Business data
    biz_dir = data_dir / "data" / "biz_mini"
    biz_dir.mkdir(parents=True)
    (biz_dir / "README.md").write_text("Mini test shop.", encoding="utf-8")
    pd.DataFrame({"id": [1, 2], "val": [10, 20]}).to_csv(biz_dir / "data.csv", index=False)

    # questions.jsonl
    q_file = data_dir / "questions.jsonl"
    questions = [
        {"id": "q_cli_1", "business_id": "biz_mini", "question": "Tong so don?", "as_of_date": "2026-08-27"},
        {"id": "q_cli_2", "business_id": "biz_mini", "question": "Gia von?", "as_of_date": "2026-08-27"},
    ]
    with q_file.open("w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q) + "\n")

    # answers.jsonl
    a_file = data_dir / "answers.jsonl"
    answers = [
        {"id": "q_cli_1", "type": "number", "answer": 2},
        {"id": "q_cli_2", "type": "unanswerable", "answer": None},
    ]
    with a_file.open("w", encoding="utf-8") as f:
        for a in answers:
            f.write(json.dumps(a) + "\n")

    return data_dir


class TestCLIIntegration:
    def test_run_inference_dry_run_streams_submission_and_logs(self, synthetic_cli_data, tmp_path):
        out_sub = tmp_path / "result" / "submission.jsonl"
        logs_dir = tmp_path / "result" / "logs"
        log_file = tmp_path / "result" / "run.log"
        work_dir = tmp_path / "result" / "tmp_work"

        cmd = [
            sys.executable,
            "-B",
            str(PROJECT_ROOT / "scripts" / "run_inference.py"),
            "--config",
            str(PROJECT_ROOT / "configs" / "default_config.yaml"),
            "--data-dir",
            str(synthetic_cli_data),
            "--output",
            str(out_sub),
            "--logs-dir",
            str(logs_dir),
            "--log-file",
            str(log_file),
            "--work-dir",
            str(work_dir),
            "--dry-run",
        ]

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env)
        assert proc.returncode == 0, f"run_inference failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        assert out_sub.exists()

        # Check submission.jsonl contents
        with out_sub.open("r", encoding="utf-8") as f:
            lines = [json.loads(line.strip()) for line in f if line.strip()]
        assert len(lines) == 2
        for item in lines:
            assert "id" in item
            assert "type" in item
            assert "answer" in item

        # Check logs directory
        assert logs_dir.exists()
        log_files = list(logs_dir.glob("*.json"))
        assert len(log_files) == 2
        log_ids = {f.stem for f in log_files}
        assert log_ids == {"q_cli_1", "q_cli_2"}

    def test_evaluate_local_cli(self, synthetic_cli_data, tmp_path):
        sub_file = tmp_path / "pred_sub.jsonl"
        predictions = [
            {"id": "q_cli_1", "type": "number", "answer": 2},
            {"id": "q_cli_2", "type": "unanswerable", "answer": None},
        ]
        with sub_file.open("w", encoding="utf-8") as f:
            for p in predictions:
                f.write(json.dumps(p) + "\n")

        cmd = [
            sys.executable,
            "-B",
            str(PROJECT_ROOT / "scripts" / "evaluate_local.py"),
            "--pred",
            str(sub_file),
            "--gold",
            str(synthetic_cli_data / "answers.jsonl"),
        ]

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env)
        assert proc.returncode == 0
        assert "PENALIZED ACCURACY (PA): 1.0000" in proc.stdout

    def test_verify_submission_cli(self, synthetic_cli_data, tmp_path):
        sub_file = tmp_path / "valid_sub.jsonl"
        predictions = [
            {"id": "q_cli_1", "type": "number", "answer": 2},
            {"id": "q_cli_2", "type": "unanswerable", "answer": None},
        ]
        with sub_file.open("w", encoding="utf-8") as f:
            for p in predictions:
                f.write(json.dumps(p) + "\n")

        cmd = [
            sys.executable,
            "-B",
            str(PROJECT_ROOT / "scripts" / "verify_submission.py"),
            "--submission",
            str(sub_file),
            "--questions",
            str(synthetic_cli_data / "questions.jsonl"),
        ]

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env)
        assert proc.returncode == 0
        assert "passed all format checks!" in proc.stdout
