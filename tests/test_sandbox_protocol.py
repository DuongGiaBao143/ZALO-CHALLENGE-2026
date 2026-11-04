"""Unit tests for bounded process runner and JSON execution protocol."""

import json
import pytest

from src.agent.sandbox import (
    ProtocolKind,
    extract_python_code,
    run_python_in_sandbox,
    validate_protocol_payload,
)


class TestExecutionProtocol:
    def test_extract_python_code(self):
        text = (
            "Here is my solution:\n"
            "```python\n"
            "import json\n"
            "print(json.dumps({'kind': 'final', 'type': 'number', 'answer': 100, 'evidence': 'test'}))\n"
            "```"
        )
        code = extract_python_code(text)
        assert code is not None
        assert "print(json.dumps" in code

    def test_validate_observation_protocol(self):
        payload = {
            "kind": "observation",
            "data": {"columns": ["a", "b"], "sample": [1, 2]},
            "message": "Found 2 columns",
        }
        kind, validated = validate_protocol_payload(payload)
        assert kind == ProtocolKind.OBSERVATION.value
        assert validated["message"] == "Found 2 columns"

    def test_validate_final_protocol_strict(self):
        # Valid final number with required evidence
        payload = {
            "kind": "final",
            "type": "number",
            "answer": 42.5,
            "evidence": "sum of 2 orders",
        }
        kind, validated = validate_protocol_payload(payload)
        assert kind == ProtocolKind.FINAL.value
        assert validated["answer"] == 42.5

        # Unanswerable enforces answer is None and requires reason and evidence
        unans_payload = {
            "kind": "final",
            "type": "unanswerable",
            "answer": "anything",
            "evidence": "checked orders.csv",
            "reason": "Missing cost column",
        }
        _, v_unans = validate_protocol_payload(unans_payload)
        assert v_unans["answer"] is None
        assert v_unans["reason"] == "Missing cost column"

    def test_reject_arbitrary_stdout_without_kind(self):
        with pytest.raises(ValueError, match="Missing required 'kind'"):
            validate_protocol_payload({"just_random_field": 123})

    def test_reject_final_without_evidence(self):
        with pytest.raises(ValueError, match="Missing or empty 'evidence'"):
            validate_protocol_payload({"kind": "final", "type": "number", "answer": 10})

    def test_reject_unanswerable_without_reason(self):
        with pytest.raises(ValueError, match="requires a non-empty 'reason'"):
            validate_protocol_payload({"kind": "final", "type": "unanswerable", "answer": None, "evidence": "checked"})

    def test_reject_nonfinite_json_values(self):
        payload = {"kind": "final", "type": "number", "answer": float("nan"), "evidence": "test"}
        with pytest.raises(ValueError, match="Non-finite"):
            validate_protocol_payload(payload)

        payload_inf = {"kind": "final", "type": "number", "answer": float("inf"), "evidence": "test"}
        with pytest.raises(ValueError, match="Non-finite"):
            validate_protocol_payload(payload_inf)


class TestProcessRunner:
    def test_runner_executes_valid_final_code(self, tmp_path):
        code = (
            "import json\n"
            "result = 10 + 20\n"
            "print(json.dumps({'kind': 'final', 'type': 'number', 'answer': result, 'evidence': 'sum arithmetic'}))\n"
        )
        res = run_python_in_sandbox(
            code=code,
            business_dir=str(tmp_path),
            work_dir=str(tmp_path / "work"),
            timeout_sec=5,
        )
        assert res.success is True
        assert res.kind == ProtocolKind.FINAL.value
        assert res.parsed_output["answer"] == 30
        assert res.parsed_output["evidence"] == "sum arithmetic"

    def test_runner_executes_observation_code(self, tmp_path):
        code = (
            "import json\n"
            "summary = {'file_count': 3, 'first_table': 'orders'}\n"
            "print(json.dumps({'kind': 'observation', 'data': summary, 'message': 'found tables'}))\n"
        )
        res = run_python_in_sandbox(
            code=code,
            business_dir=str(tmp_path),
            work_dir=str(tmp_path / "work"),
            timeout_sec=5,
        )
        assert res.success is True
        assert res.kind == ProtocolKind.OBSERVATION.value
        assert res.parsed_output["data"]["file_count"] == 3

    def test_runner_captures_runtime_errors(self, tmp_path):
        code = "raise KeyError('UnknownColumn')"
        res = run_python_in_sandbox(
            code=code,
            business_dir=str(tmp_path),
            work_dir=str(tmp_path / "work"),
            timeout_sec=5,
        )
        assert res.success is False
        assert res.kind == ProtocolKind.ERROR.value
        assert res.error_kind == "runtime_error"
        assert "KeyError" in res.error_message
        assert res.returncode != 0

    def test_runner_enforces_timeout(self, tmp_path):
        code = "import time\ntime.sleep(10)"
        res = run_python_in_sandbox(
            code=code,
            business_dir=str(tmp_path),
            work_dir=str(tmp_path / "work"),
            timeout_sec=1,
        )
        assert res.success is False
        assert res.timeout is True
        assert res.error_kind == "timeout"
        assert "exceeded 1 seconds" in res.error_message

    def test_runner_rejects_arbitrary_stdout(self, tmp_path):
        code = "print('Hello world without protocol')"
        res = run_python_in_sandbox(
            code=code,
            business_dir=str(tmp_path),
            work_dir=str(tmp_path / "work"),
            timeout_sec=5,
        )
        assert res.success is False
        assert res.error_kind == "protocol_violation"

    def test_runner_handles_smart_path_int64_indent_and_list_type_coercion(self, tmp_path):
        (tmp_path / "orders.csv").write_text("val\n10\n20\n", encoding="utf-8")
        code = (
            "df = pd.read_csv(BUSINESS_DIR / 'orders.csv')\n"
            "s = df['val'].sum()\n"  # np.int64
            "print(json.dumps({'kind': 'final', 'type': 'number', 'answer': [s, s * 2], 'evidence': 'orders.csv'}, indent=4))\n"
        )
        res = run_python_in_sandbox(
            code=code,
            business_dir=str(tmp_path),
            work_dir=str(tmp_path / "work"),
            timeout_sec=5,
        )
        assert res.success is True
        assert res.parsed_output["type"] == "list"
        assert res.parsed_output["answer"] == [30, 60]

    def test_runner_handles_vn_date_comparison_and_string_number_sum(self, tmp_path):
        code = (
            "df = pd.DataFrame({'ngay': ['1 thg 4 2026', '02/04/2026', '15/03/2026'], 'tien': ['100,000', '250,000', '50,000']})\n"
            "filtered = df[df['ngay'] >= parse_vn_date('01/04/2026')]\n"
            "total = filtered['tien'].sum()\n"
            "print(json.dumps({'kind': 'final', 'type': 'number', 'answer': total, 'evidence': 'synthetic df'}))\n"
        )
        res = run_python_in_sandbox(
            code=code,
            business_dir=str(tmp_path),
            work_dir=str(tmp_path / "work"),
            timeout_sec=5,
        )
        assert res.success is True
        assert res.parsed_output["answer"] == 350000
