"""Independent boundary checks for generated execution results."""
import pytest

from src.agent.sandbox import validate_protocol_payload, run_python_in_sandbox


@pytest.mark.parametrize("payload", [
    {"type": "number", "answer": 1, "evidence": "read orders.csv"},
    {"kind": "final", "type": "string", "answer": {"unexpected": 1}, "evidence": "read orders.csv"},
    {"kind": "final", "type": "date", "answer": "2026-02-31", "evidence": "read orders.csv"},
    {"kind": "final", "type": "table", "answer": {"columns": ["name", "qty"], "rows": [["Lan"]]}, "evidence": "read orders.csv"},
    {"kind": "final", "type": "list", "answer": [{"nested": 1}], "evidence": "read orders.csv"},
    {"kind": "final", "type": "number", "answer": 1},
    {"kind": "final", "type": "unanswerable", "answer": None, "evidence": "checked orders.csv"},
    {"kind": "observation", "data": [1], "message": {"not": "a string"}},
])
def test_invalid_payloads_cannot_pass_boundary(payload):
    with pytest.raises(ValueError):
        validate_protocol_payload(payload)


def test_runner_never_resurrects_an_earlier_valid_answer(tmp_path):
    code = '''print(json.dumps({"kind":"final","type":"number","answer":1,"evidence":"synthetic.csv"}))
print('{"kind":"final","type":"number","answer":NaN,"evidence":"synthetic.csv"}')'''
    result = run_python_in_sandbox(code, str(tmp_path), work_dir=str(tmp_path / "work"))
    assert not result.success, "A malformed final line must not select an earlier candidate."
