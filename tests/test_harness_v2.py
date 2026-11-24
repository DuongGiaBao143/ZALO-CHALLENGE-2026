from pathlib import Path

from harness_v2.evalsets import EvalSet
from harness_v2.run import abstain, run
from harness_v2.score import load_preds, score_set


def _es(tmp_path: Path) -> EvalSet:
    items = [{"id": f"q{i}", "business_id": "b", "question": "?", "as_of_date": "2026-01-01"} for i in range(3)]
    gold = {"q0": {"id": "q0", "type": "number", "answer": 5, "alias": []},
            "q1": {"id": "q1", "type": "number", "answer": 7, "alias": []},
            "q2": {"id": "q2", "type": "unanswerable", "answer": None, "alias": []}}
    return EvalSet("t", tmp_path, items, gold)


def test_score_counts_correct_wrong_abstain():
    es = _es(Path("."))
    preds = {"q0": {"id": "q0", "type": "number", "answer": 5}, "q1": {"id": "q1", "type": "number", "answer": 9}}
    rep = score_set(es, preds)   # q2 không có dự đoán -> abstain
    assert (rep["correct"], rep["wrong"], rep["abstain"]) == (1, 1, 1)
    assert rep["PA"] == 0.0 and rep["abstain_reasons"] == {"no_prediction": 1}


def test_run_resumes_and_survives_solver_errors(tmp_path):
    es = _es(tmp_path)
    out = tmp_path / "p.jsonl"
    calls = []

    def solve(item, split_dir):
        calls.append(item["id"])
        if item["id"] == "q1":
            raise RuntimeError("boom")
        return {"type": "number", "answer": 5} if item["id"] == "q0" else abstain("x")

    run(es, solve, out, workers=2)
    assert sorted(calls) == ["q0", "q1", "q2"]
    assert load_preds(out)["q1"]["reason"] == "solver_error:RuntimeError"
    run(es, solve, out, workers=2)   # chạy lại: không gọi solver nữa
    assert len(calls) == 3
