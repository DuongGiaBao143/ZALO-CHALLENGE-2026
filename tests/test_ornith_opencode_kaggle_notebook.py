"""Tests for the Ornith 1.5 + OpenCode Kaggle 2xT4 evaluation notebook and tool bridge."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "Evaluate_Ornith_OpenCode_Kaggle_2T4.ipynb"
STRUCTURED_DIR = REPO_ROOT / "tmp" / "opencode-structured"
BRIDGE_PATH = STRUCTURED_DIR / "bridge.py"


def _load_notebook_cells() -> list[dict]:
    assert NOTEBOOK_PATH.is_file(), f"Missing notebook: {NOTEBOOK_PATH}"
    nb = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    assert nb.get("nbformat") == 4
    return nb["cells"]


def _load_cell3_normalizer_namespace() -> dict:
    """Compile and exec pure helper definitions from Cell 3 of the notebook."""
    cells = _load_notebook_cells()
    cell3_src = "".join(cells[3]["source"])
    # Strip top-level execution lines that load SPLIT_DIR/questions.jsonl
    tree = ast.parse(cell3_src)
    keep_nodes = [
        node for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign))
        and not (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "ALL_QUESTIONS" for t in node.targets)
        )
    ]
    mod = ast.Module(body=keep_nodes, type_ignores=[])
    code = compile(mod, filename=str(NOTEBOOK_PATH), mode="exec")

    sys.path.insert(0, str(STRUCTURED_DIR))
    sys.path.append(str(REPO_ROOT))
    from src.agent.sandbox import validate_protocol_payload
    from src.schemas import AnswerType, QuestionItem, SubmissionItem, VALID_ANSWER_TYPES

    ns = {
        "Path": Path,
        "json": json,
        "shutil": __import__("shutil"),
        "subprocess": subprocess,
        "sys": sys,
        "os": os,
        "validate_protocol_payload": validate_protocol_payload,
        "AnswerType": AnswerType,
        "QuestionItem": QuestionItem,
        "SubmissionItem": SubmissionItem,
        "VALID_ANSWER_TYPES": VALID_ANSWER_TYPES,
        "OPENCODE_RUNTIME_DIR": STRUCTURED_DIR,
        "PRE_STAGED_NODE_MODULES": None,
    }
    exec(code, ns)
    return ns


def test_notebook_structure_syntax_and_manifests() -> None:
    cells = _load_notebook_cells()
    assert len(cells) == 7

    code_cells = [c for c in cells if c.get("cell_type") == "code"]
    assert len(code_cells) == 6
    for idx, cell in enumerate(code_cells):
        src = "".join(cell["source"])
        ast.parse(src, filename=f"cell_{idx}")

    # Verify embedded manifests match gold/train datasets
    cell1_src = "".join(code_cells[0]["source"])
    cell1_tree = ast.parse(cell1_src)
    assigns = {}
    config_nodes = {}
    for node in cell1_tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in (
                "MANIFEST_50_IDS",
                "CSV_COUNT_DISTINCT_HOLDOUT_IDS",
                "SMOKE_AGGREGATE_QID",
                "SMOKE_RUN_PYTHON_QID",
                "SMOKE_RUN_PYTHON_EXPECTED",
                "RUN_SMOKE_TESTS",
                "SMOKE_SINGLE_QUESTION_ONLY",
                "RUN_BATCH_EVAL",
                "ENABLE_DUAL_WORKER_BENCHMARK",
                "PARALLEL_SLOTS_PER_GPU",
                "NUM_WORKERS",
                "NUM_BATCH",
                "FAIL_FAST_ON_SMOKE_ERROR",
                "REQUIRE_SMOKE_PASS_FOR_BATCH",
            ):
                assigns[name] = ast.literal_eval(node.value)
            elif name in ("EXECUTION_STAGE", "TOOL_MODE", "ALLOW_EXPOSED_REFERENCE_IN_RUN_PYTHON"):
                config_nodes[name] = node.value

    class _CleanOS:
        environ: dict[str, str] = {}

    assert eval(compile(ast.Expression(config_nodes["EXECUTION_STAGE"]), str(NOTEBOOK_PATH), "eval"), {"os": _CleanOS()}) == "inference"
    assert eval(compile(ast.Expression(config_nodes["TOOL_MODE"]), str(NOTEBOOK_PATH), "eval"), {"os": _CleanOS()}) == "eval_agent"
    assert eval(compile(ast.Expression(config_nodes["ALLOW_EXPOSED_REFERENCE_IN_RUN_PYTHON"]), str(NOTEBOOK_PATH), "eval"), {"os": _CleanOS()}) is False

    # Both smoke questions run by default. Ollama allows one qwen35 request per daemon.
    assert assigns["RUN_SMOKE_TESTS"] is True
    assert assigns["SMOKE_SINGLE_QUESTION_ONLY"] is False
    assert assigns["RUN_BATCH_EVAL"] is False
    assert assigns["ENABLE_DUAL_WORKER_BENCHMARK"] is False
    assert assigns["PARALLEL_SLOTS_PER_GPU"] == 1
    assert assigns["NUM_WORKERS"] == 2
    assert assigns["NUM_BATCH"] == 128
    assert assigns["FAIL_FAST_ON_SMOKE_ERROR"] is True
    assert assigns["REQUIRE_SMOKE_PASS_FOR_BATCH"] is True

    cell4_src = "".join(code_cells[3]["source"])
    cell5_src = "".join(code_cells[4]["source"])
    assert "if not SMOKE_PASSED and FAIL_FAST_ON_SMOKE_ERROR:" in cell4_src
    assert "print_smoke_failure_details" in cell4_src
    assert "if REQUIRE_SMOKE_PASS_FOR_BATCH and RUN_SMOKE_TESTS and not SMOKE_PASSED:" in cell5_src
    assert "queue.Queue()" in cell5_src
    assert "_warmup_worker_tag" in cell5_src
    assert "active_slots" in cell5_src

    gold_50 = {
        row["id"]: row
        for row in (json.loads(line) for line in (REPO_ROOT / "eval_gold" / "unseen_gold_50.jsonl").read_text(encoding="utf-8-sig").splitlines() if line.strip())
    }
    assert assigns["MANIFEST_50_IDS"] == list(gold_50)
    assert len(assigns["MANIFEST_50_IDS"]) == 50
    assert len(assigns["CSV_COUNT_DISTINCT_HOLDOUT_IDS"]) == 12
    assert assigns["SMOKE_AGGREGATE_QID"] == "q_5c19a3193881"
    assert assigns["SMOKE_RUN_PYTHON_QID"] == "q_01a28f2233bd"
    smoke_gold = gold_50[assigns["SMOKE_RUN_PYTHON_QID"]]
    assert assigns["SMOKE_RUN_PYTHON_EXPECTED"] == (smoke_gold["type"], smoke_gold["answer"])

    # Verify all CSV holdout IDs exist in train and belong to the 4 holdout CSV shops
    train_qs = {
        row["id"]: row
        for row in (json.loads(l) for l in (REPO_ROOT / "data" / "train" / "questions.jsonl").read_text(encoding="utf-8-sig").splitlines() if l.strip())
    }
    assert all(qid in train_qs for qid in assigns["CSV_COUNT_DISTINCT_HOLDOUT_IDS"])
    assert {train_qs[qid]["business_id"] for qid in assigns["CSV_COUNT_DISTINCT_HOLDOUT_IDS"]} == {
        "biz_111", "biz_114", "biz_127", "biz_129"
    }

    # Verify embedded runtime templates in Cell 1 match tmp/opencode-structured/ byte-for-byte
    embedded_map = {}
    for node in cell1_tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.startswith("EMBEDDED_"):
                embedded_map[name] = ast.literal_eval(node.value)
    assert embedded_map["EMBEDDED_RUN_JS"] == (STRUCTURED_DIR / "run.js").read_text(encoding="utf-8")
    assert embedded_map["EMBEDDED_INSPECT_TABLE_JS"] == (STRUCTURED_DIR / "tools" / "inspect_table.js").read_text(encoding="utf-8")
    assert embedded_map["EMBEDDED_AGGREGATE_JS"] == (STRUCTURED_DIR / "tools" / "aggregate.js").read_text(encoding="utf-8")
    assert embedded_map["EMBEDDED_RUN_PYTHON_JS"] == (STRUCTURED_DIR / "tools" / "run_python.js").read_text(encoding="utf-8")
    assert embedded_map["EMBEDDED_EXPLORE_DATA_JS"] == (STRUCTURED_DIR / "tools" / "explore_data.js").read_text(encoding="utf-8")
    assert embedded_map["EMBEDDED_BRIDGE_PY"] == (STRUCTURED_DIR / "bridge.py").read_text(encoding="utf-8")


def test_structured_tool_declarations_exist() -> None:
    run_js = (STRUCTURED_DIR / "run.js").read_text(encoding="utf-8")
    assert "DATAMATE_PYTHON_BIN" in run_js
    assert "DATAMATE_BRIDGE_PATH" in run_js
    assert "DATAMATE_TOOL_TIMEOUT_MS" in run_js

    run_py_js = (STRUCTURED_DIR / "tools" / "run_python.js").read_text(encoding="utf-8")
    assert 'run("run_python", args)' in run_py_js
    assert "emit_final" in run_py_js


def test_bridge_end_to_end_on_biz_125(tmp_path: Path) -> None:
    biz_125_dir = REPO_ROOT / "data" / "train" / "data" / "biz_125"
    trace_file = tmp_path / "tool_trace.jsonl"
    work_dir = tmp_path / "py_work"
    env = {
        **os.environ,
        "DATAMATE_DATA_ROOT": str(biz_125_dir.resolve()),
        "DATAMATE_SRC_ROOT": str(STRUCTURED_DIR.resolve()),
        "DATAMATE_WORK_DIR": str(work_dir),
        "DATAMATE_AS_OF_DATE": "2026-04-14",
        "DATAMATE_RULEBOOK_PATH": str((REPO_ROOT / "data" / "train" / "rulebook.md").resolve()),
        "DATAMATE_CALENDAR_PATH": str((REPO_ROOT / "data" / "train" / "calendar.csv").resolve()),
        "DATAMATE_TOOL_TRACE_PATH": str(trace_file),
    }

    def invoke(action: str, payload: dict) -> dict:
        proc = subprocess.run(
            [sys.executable, str(BRIDGE_PATH), action, json.dumps(payload, ensure_ascii=False)],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=30,
        )
        return json.loads(proc.stdout.strip())

    # 1. inspect_table schema & labels
    schema = invoke("inspect_table", {"file": None, "column": None})
    assert schema["file"] == "ban_hang.csv"
    assert "Số phiếu" in schema["columns"]

    labels = invoke("inspect_table", {"file": "ban_hang.csv", "column": "Trạng thái xử lý"})
    assert set(labels["unique_values"]) == {"Đã hoàn thành", "Huỷ đơn", "Đã trả hàng", "Đang xử lý"}

    # 2. aggregate count_distinct (q_5c19a3193881)
    agg = invoke(
        "aggregate",
        {
            "file": "ban_hang.csv",
            "operation": "count_distinct",
            "date_column": "Ngày bán",
            "date_expression": "ngày hôm nay",
            "as_of_date": "2025-03-28",
            "column": "Số phiếu",
            "status_column": "Trạng thái xử lý",
            "exclude_values": ["Huỷ đơn", "Đã trả hàng"],
        },
    )
    assert agg["type"] == "number"
    assert agg["answer"] == 41

    # 3. run_python on non-count_distinct question (q_8f16268d281c: 2026-04-14 revenue)
    py_code = """
df = load_clean_df('ban_hang.csv', id_col='Số phiếu', date_col='Ngày bán', dedup_order=False)
period = resolve_date('ngày hôm nay', as_of_date=AS_OF_DATE)
dates = parse_vn_date(df['Ngày bán'], default_year=df.attrs.get('default_year'))
start = pd.Timestamp(period['start_date'])
stop = pd.Timestamp(period['end_date']) + pd.Timedelta(days=1)
in_day = dates.ge(start) & dates.lt(stop)
bad_ids = set(df.loc[in_day & df['Trạng thái xử lý'].isin(['Huỷ đơn', 'Đã trả hàng']), 'Số phiếu'].dropna())
valid = df[in_day & ~df['Số phiếu'].isin(bad_ids)]
rev = float(valid['Amount'].sum())
emit_final(int(round(rev)), type='number', evidence='Sum Amount excluding cancelled/returned orders on 2026-04-14')
"""
    py_res = invoke("run_python", {"code": py_code})
    assert py_res["success"] is True, py_res
    assert py_res["kind"] == "final"
    assert py_res["parsed_output"]["answer"] == 21563000

    # Verify untruncated sidecar trace captured all 4 calls
    trace_lines = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [t["action"] for t in trace_lines] == ["inspect_table", "inspect_table", "aggregate", "run_python"]
    assert trace_lines[-1]["result"]["parsed_output"]["answer"] == 21563000


def test_section4_event_parser_and_normalizer() -> None:
    ns = _load_cell3_normalizer_namespace()
    parse_events = ns["parse_opencode_jsonl_events"]
    normalize_final = ns["normalize_final_answer"]

    # Case 1: biz_125 t0 log -> bare "41" matches aggregate -> type_source == "tool:aggregate"
    log_t0 = (REPO_ROOT / "tmp" / "opencode-ornith15-biz125-question-only-t0.jsonl").read_text(encoding="utf-8")
    parsed_t0 = parse_events(log_t0)
    assert parsed_t0["raw_final_text"] == "41"
    norm_t0 = normalize_final("q_5c19a3193881", parsed_t0["raw_final_text"], parsed_t0["tool_calls"])
    assert norm_t0["prediction"] == {"id": "q_5c19a3193881", "type": "number", "answer": 41}
    assert norm_t0["type_source"] == "tool:aggregate"
    assert norm_t0["tool_succeeded_but_final_empty"] is False

    # Case 2: biz_125 t0.4 log -> empty final with valid aggregate -> abstain + tool_succeeded_but_final_empty
    log_t04 = (REPO_ROOT / "tmp" / "opencode-ornith15-biz125-question-only-t04.jsonl").read_text(encoding="utf-8")
    parsed_t04 = parse_events(log_t04)
    assert parsed_t04["raw_final_text"] == ""
    norm_t04 = normalize_final("q_5c19a3193881", parsed_t04["raw_final_text"], parsed_t04["tool_calls"])
    assert norm_t04["prediction"] == {"id": "q_5c19a3193881", "type": "abstain", "answer": None}
    assert norm_t04["type_source"] == "abstain"
    assert norm_t04["abstain_reason"] == "empty_final"
    assert norm_t04["tool_succeeded_but_final_empty"] is True
    assert norm_t04["tool_rescue_prediction"] == {"id": "q_5c19a3193881", "type": "number", "answer": 41}

    # Case 3: biz_101 structured t0 log -> explicit JSON {"type":"number","answer":37} -> type_source == "model"
    log_101 = (REPO_ROOT / "tmp" / "opencode-ornith15-biz101-structured-t0.jsonl").read_text(encoding="utf-8")
    parsed_101 = parse_events(log_101)
    norm_101 = normalize_final("q_0cb7c9b93048", parsed_101["raw_final_text"], parsed_101["tool_calls"])
    assert norm_101["prediction"] == {"id": "q_0cb7c9b93048", "type": "number", "answer": 37}
    assert norm_101["type_source"] == "model"

    # Case 4: bare value matching validated run_python final payload -> type_source == "tool:run_python"
    py_tool_calls = [
        {
            "tool": "run_python",
            "status": "completed",
            "full_result": {
                "success": True,
                "kind": "final",
                "parsed_output": {
                    "kind": "final",
                    "type": "number",
                    "answer": 21563000,
                    "evidence": "Sum revenue",
                },
            },
        }
    ]
    norm_py = normalize_final("q_8f16268d281c", "21563000", py_tool_calls)
    assert norm_py["prediction"] == {"id": "q_8f16268d281c", "type": "number", "answer": 21563000}
    assert norm_py["type_source"] == "tool:run_python"

    # Case 5: bare ambiguous value 12.5 without matching validated tool payload -> abstain
    norm_ambig = normalize_final("q_ambig", "12.5", [])
    assert norm_ambig["prediction"] == {"id": "q_ambig", "type": "abstain", "answer": None}
    assert norm_ambig["type_source"] == "abstain"
    assert norm_ambig["abstain_reason"] == "ambiguous_type_without_matching_tool"


def test_cell6_scorer_aggregation(tmp_path: Path) -> None:
    cells = _load_notebook_cells()
    cell6_src = "".join(cells[6]["source"])
    tree = ast.parse(cell6_src)
    keep_nodes = [
        node for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))
    ]
    mod = ast.Module(body=keep_nodes, type_ignores=[])
    code = compile(mod, filename=str(NOTEBOOK_PATH), mode="exec")

    sys.path.insert(0, str(REPO_ROOT))
    from src.eval.scorer import evaluate_predictions
    from src.schemas import QuestionItem

    ns = {
        "Path": Path,
        "json": json,
        "SPLIT_DIR": REPO_ROOT / "data" / "train",
        "evaluate_predictions": evaluate_predictions,
        "ALL_QUESTIONS": {
            "q_5c19a3193881": QuestionItem("q_5c19a3193881", "biz_125", "q1", "2025-03-28"),
            "q_0c20dcf7fc9f": QuestionItem("q_0c20dcf7fc9f", "biz_127", "q2", "2026-07-28"),
        },
    }
    exec(code, ns)

    sub_dir = tmp_path / "run_x"
    (sub_dir / "traces").mkdir(parents=True)
    (sub_dir / "manifest.json").write_text(json.dumps({
        "run_label": "test_run",
        "tool_mode": "eval_agent",
        "temperature": 0.0,
        "question_ids": ["q_5c19a3193881", "q_0c20dcf7fc9f"],
        "total_elapsed_sec": 12.5,
    }), encoding="utf-8")
    (sub_dir / "predictions.jsonl").write_text(
        json.dumps({"id": "q_5c19a3193881", "type": "number", "answer": 41}) + "\n"
        + json.dumps({"id": "q_0c20dcf7fc9f", "type": "abstain", "answer": None}) + "\n",
        encoding="utf-8",
    )
    (sub_dir / "traces" / "q_5c19a3193881.json").write_text(json.dumps({
        "type_source": "tool:aggregate",
        "abstain_reason": None,
        "tool_succeeded_but_final_empty": False,
    }), encoding="utf-8")
    (sub_dir / "traces" / "q_0c20dcf7fc9f.json").write_text(json.dumps({
        "type_source": "abstain",
        "abstain_reason": "empty_final",
        "tool_succeeded_but_final_empty": True,
        "tool_rescue_prediction": {"id": "q_0c20dcf7fc9f", "type": "date", "answer": "2025-12-07"},
    }), encoding="utf-8")

    ref_map = {
        "q_5c19a3193881": {"id": "q_5c19a3193881", "type": "number", "answer": 41},
        "q_0c20dcf7fc9f": {"id": "q_0c20dcf7fc9f", "type": "date", "answer": "2025-12-07"},
    }
    rep = ns["score_run_dir"](sub_dir, ref_map)
    assert rep["scored_total"] == 2
    assert rep["correct"] == 1
    assert rep["abstain"] == 1
    assert rep["wrong"] == 0
    assert rep["pa"] == 0.5
    assert rep["tool_succeeded_but_final_empty"] == 1
    assert rep["shadow_tool_rescue"]["pa"] == 1.0
    assert rep["by_format"]["csv"]["pa"] == 0.5


def test_finding1_prepare_isolated_shop_root_copies_real_files_and_passes_bridge_guard(tmp_path: Path) -> None:
    ns = _load_cell3_normalizer_namespace()
    prepare_isolated_shop_root = ns["prepare_isolated_shop_root"]
    QuestionItem = ns["QuestionItem"]
    remove_ro = ns["_remove_readonly_tree"]

    q = QuestionItem("q_5c19a3193881", "biz_125", "Hôm nay có bao nhiêu đơn?", "2025-03-28")
    root_base = tmp_path / "isolated_shops"
    shop_root = prepare_isolated_shop_root(q, REPO_ROOT / "data" / "train", root_base)

    copied = list(shop_root.iterdir())
    assert copied
    assert (shop_root / "ban_hang.csv").is_file()
    assert (shop_root / "README.md").is_file()
    for p in copied:
        assert p.is_file()
        assert not p.is_symlink()
        assert p.resolve().is_relative_to(shop_root.resolve())

    # Second run must cleanly replace the read-only (0o444) files copied by the first run
    shop_root_2 = prepare_isolated_shop_root(q, REPO_ROOT / "data" / "train", root_base)
    assert shop_root_2 == shop_root

    env = {
        **os.environ,
        "DATAMATE_DATA_ROOT": str(shop_root_2.resolve()),
        "DATAMATE_SRC_ROOT": str(STRUCTURED_DIR.resolve()),
        "DATAMATE_WORK_DIR": str(tmp_path / "py_work"),
        "DATAMATE_AS_OF_DATE": "2025-03-28",
        "DATAMATE_RULEBOOK_PATH": str((REPO_ROOT / "data" / "train" / "rulebook.md").resolve()),
        "DATAMATE_CALENDAR_PATH": str((REPO_ROOT / "data" / "train" / "calendar.csv").resolve()),
    }

    def invoke(action: str, payload: dict) -> dict:
        proc = subprocess.run(
            [sys.executable, str(BRIDGE_PATH), action, json.dumps(payload, ensure_ascii=False)],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=30,
        )
        return json.loads(proc.stdout.strip())

    try:
        schema = invoke("inspect_table", {"file": None, "column": None})
        assert schema["file"] == "ban_hang.csv"
        agg = invoke(
            "aggregate",
            {
                "file": "ban_hang.csv",
                "operation": "count_distinct",
                "date_column": "Ngày bán",
                "date_expression": "ngày hôm nay",
                "as_of_date": "2025-03-28",
                "column": "Số phiếu",
                "status_column": "Trạng thái xử lý",
                "exclude_values": ["Huỷ đơn", "Đã trả hàng"],
            },
        )
        assert agg["type"] == "number"
        assert agg["answer"] == 41
    finally:
        remove_ro(root_base)


def test_finding2_ollama_tar_zst_and_extract_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import shutil
    import tarfile
    import zipfile

    cells = _load_notebook_cells()
    cell2_src = "".join(cells[2]["source"])
    assert "ollama-linux-amd64.tar.zst" in cell2_src
    assert "ollama-linux-amd64.tgz" not in cell2_src

    tree = ast.parse(cell2_src)
    fn_node = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "extract_archive"
    )
    mod = ast.Module(body=[fn_node], type_ignores=[])
    ns = {
        "Path": Path,
        "subprocess": subprocess,
        "shutil": shutil,
        "tarfile": tarfile,
        "zipfile": zipfile,
    }
    exec(compile(mod, str(NOTEBOOK_PATH), "exec"), ns)
    extract_archive = ns["extract_archive"]

    # .tar.gz extraction
    tgz_path = tmp_path / "sample.tar.gz"
    with tarfile.open(tgz_path, "w:gz") as tf:
        data = b"ollama-ok"
        ti = tarfile.TarInfo("bin/hello.txt")
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    out_tgz = tmp_path / "out_tgz"
    extract_archive(tgz_path, out_tgz)
    assert (out_tgz / "bin" / "hello.txt").read_text(encoding="utf-8") == "ollama-ok"

    # .zip extraction
    zip_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("sub/item.txt", "opencode-ok")
    out_zip = tmp_path / "out_zip"
    extract_archive(zip_path, out_zip)
    assert (out_zip / "sub" / "item.txt").read_text(encoding="utf-8") == "opencode-ok"

    # .tar.zst dispatch invokes tar --zstd
    seen_cmds = []

    class _Proc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen_cmds.append(cmd)
        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    zst_path = tmp_path / "ollama-linux-amd64.tar.zst"
    zst_path.write_bytes(b"placeholder")
    out_zst = tmp_path / "out_zst"
    extract_archive(zst_path, out_zst)
    assert seen_cmds == [["tar", "--zstd", "-xf", str(zst_path), "-C", str(out_zst)]]

    # Unsupported extension fails explicitly
    bad_path = tmp_path / "unknown.rar"
    bad_path.write_bytes(b"x")
    with pytest.raises(ValueError):
        extract_archive(bad_path, tmp_path / "out_bad")


def test_finding3_scan_exposed_reference_files_and_guard(tmp_path: Path) -> None:
    cells = _load_notebook_cells()
    cell1_src = "".join(cells[1]["source"])
    tree = ast.parse(cell1_src)

    scan_fn = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "scan_exposed_reference_files"
    )
    guard_if = next(
        n for n in tree.body
        if isinstance(n, ast.If)
        and "ALLOW_EXPOSED_REFERENCE_IN_RUN_PYTHON" in (ast.get_source_segment(cell1_src, n) or "")
    )

    ns = {"Path": Path}
    exec(compile(ast.Module(body=[scan_fn], type_ignores=[]), str(NOTEBOOK_PATH), "exec"), ns)
    scan = ns["scan_exposed_reference_files"]

    d1 = tmp_path / "input_split"
    d2 = tmp_path / "input_eval"
    (d1 / "data" / "biz_1").mkdir(parents=True)
    (d1 / ".git").mkdir(parents=True)
    (d2 / "eval_gold").mkdir(parents=True)

    ans1 = d1 / "answers.jsonl"
    ans1.write_text("{}\n", encoding="utf-8")
    gold2 = d2 / "eval_gold" / "unseen_gold_50.jsonl"
    gold2.write_text("{}\n", encoding="utf-8")
    (d1 / "data" / "biz_1" / "ban_hang.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (d1 / ".git" / "answers.jsonl").write_text("{}\n", encoding="utf-8")

    detected = scan([d1], [d2])
    assert set(detected) == {ans1.resolve(), gold2.resolve()}

    guard_code = compile(ast.Module(body=[guard_if], type_ignores=[]), str(NOTEBOOK_PATH), "exec")

    # 1. Inference + eval_agent + exposed ref + ALLOW=False -> PREFLIGHT_ERRORS
    g_ns = {
        "EXECUTION_STAGE": "inference",
        "TOOL_MODE": "eval_agent",
        "EXPOSED_REFERENCE_FILES": detected,
        "ALLOW_EXPOSED_REFERENCE_IN_RUN_PYTHON": False,
        "PREFLIGHT_ERRORS": [],
        "PREFLIGHT_WARNINGS": [],
    }
    exec(guard_code, g_ns)
    assert len(g_ns["PREFLIGHT_ERRORS"]) == 1
    assert g_ns["PREFLIGHT_WARNINGS"] == []

    # 2. Override ALLOW=True -> warning only
    g_ns_warn = {
        "EXECUTION_STAGE": "inference",
        "TOOL_MODE": "eval_agent",
        "EXPOSED_REFERENCE_FILES": detected,
        "ALLOW_EXPOSED_REFERENCE_IN_RUN_PYTHON": True,
        "PREFLIGHT_ERRORS": [],
        "PREFLIGHT_WARNINGS": [],
    }
    exec(guard_code, g_ns_warn)
    assert g_ns_warn["PREFLIGHT_ERRORS"] == []
    assert len(g_ns_warn["PREFLIGHT_WARNINGS"]) == 1

    # 3. structured_only or score_only -> allowed cleanly
    for stage, mode in [("inference", "structured_only"), ("score_only", "eval_agent")]:
        g_ns_ok = {
            "EXECUTION_STAGE": stage,
            "TOOL_MODE": mode,
            "EXPOSED_REFERENCE_FILES": detected,
            "ALLOW_EXPOSED_REFERENCE_IN_RUN_PYTHON": False,
            "PREFLIGHT_ERRORS": [],
            "PREFLIGHT_WARNINGS": [],
        }
        exec(guard_code, g_ns_ok)
        assert g_ns_ok["PREFLIGHT_ERRORS"] == []
        assert g_ns_ok["PREFLIGHT_WARNINGS"] == []


def test_finding4_conflicting_tool_types_resolution() -> None:
    ns = _load_cell3_normalizer_namespace()
    normalize_final = ns["normalize_final_answer"]

    def _agg_call(msg_id: str, ans: int | float, typ: str = "number") -> dict:
        return {
            "tool": "aggregate",
            "status": "completed",
            "messageID": msg_id,
            "full_result": {"type": typ, "answer": ans},
        }

    def _py_call(msg_id: str, ans: int | float, typ: str) -> dict:
        return {
            "tool": "run_python",
            "status": "completed",
            "messageID": msg_id,
            "full_result": {
                "success": True,
                "kind": "final",
                "parsed_output": {
                    "kind": "final",
                    "type": typ,
                    "answer": ans,
                    "evidence": "computed",
                },
            },
        }

    # 1. aggregate -> run_python (final calculation) with same value 12 -> percent wins
    r1 = normalize_final("q1", "12", [_agg_call("msg_1", 12, "number"), _py_call("msg_2", 12, "percent")])
    assert r1["prediction"] == {"id": "q1", "type": "percent", "answer": 12}
    assert r1["type_source"] == "tool:run_python"

    # 2. run_python -> aggregate (final calculation) with same value 12 -> number wins
    r2 = normalize_final("q2", "12", [_py_call("msg_1", 12, "percent"), _agg_call("msg_2", 12, "number")])
    assert r2["prediction"] == {"id": "q2", "type": "number", "answer": 12}
    assert r2["type_source"] == "tool:aggregate"

    # 3. Same-turn messageID conflict -> abstain
    r3 = normalize_final("q3", "12", [_agg_call("msg_1", 12, "number"), _py_call("msg_1", 12, "percent")])
    assert r3["prediction"] == {"id": "q3", "type": "abstain", "answer": None}
    assert r3["type_source"] == "abstain"
    assert r3["abstain_reason"] == "conflicting_tool_types"

    # 4. Later non-matching verified computation -> matching choice isn't overall last -> abstain
    r4 = normalize_final(
        "q4",
        "12",
        [_agg_call("msg_1", 12, "number"), _py_call("msg_2", 12, "percent"), _agg_call("msg_3", 99, "number")],
    )
    assert r4["prediction"] == {"id": "q4", "type": "abstain", "answer": None}
    assert r4["type_source"] == "abstain"
    assert r4["abstain_reason"] == "conflicting_tool_types"


def test_hf_bundle_config_and_no_hardcoded_token() -> None:
    import re

    nb_text = NOTEBOOK_PATH.read_text(encoding="utf-8")
    upload_script_text = (REPO_ROOT / "scripts" / "upload_ornith_opencode_hf_bundle.py").read_text(encoding="utf-8")
    token_re = re.compile(r"hf_[A-Za-z0-9]{15,}")
    assert not token_re.search(nb_text), "Hardcoded HF token detected in notebook!"
    assert not token_re.search(upload_script_text), "Hardcoded HF token detected in upload script!"

    cells = _load_notebook_cells()
    cell1_src = "".join(cells[1]["source"])
    cell2_src = "".join(cells[2]["source"])
    cell3_src = "".join(cells[3]["source"])

    tree = ast.parse(cell1_src)
    vals = {}
    exprs = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("HF_INFERENCE_BUNDLE_PATH", "HF_REFERENCE_BUNDLE_PATH", "HF_OLLAMA_BLOBS_PREFIX"):
                vals[name] = ast.literal_eval(node.value)
            elif name == "HF_DATASET_REPO":
                exprs[name] = node.value

    class _CleanOS:
        environ: dict[str, str] = {}

    assert eval(compile(ast.Expression(exprs["HF_DATASET_REPO"]), str(NOTEBOOK_PATH), "eval"), {"os": _CleanOS()}) == "Crinkk/Zalo-challenge"
    assert vals["HF_INFERENCE_BUNDLE_PATH"] == "ornith_opencode_kaggle/ornith_opencode_inference_bundle_v3.zip"
    assert vals["HF_REFERENCE_BUNDLE_PATH"] == "ornith_opencode_kaggle/ornith_opencode_reference_bundle.zip"
    assert vals["HF_OLLAMA_BLOBS_PREFIX"] == "ornith_opencode_kaggle/ollama_blobs"

    # Verify download_from_hf tries model with token and falls back cleanly to public dataset with token=False
    assert 'attempts.append(("model", tok))' in cell1_src
    assert 'attempts.append(("dataset", False))' in cell1_src
    assert "HF_STAGE2_REF_DIR" in cell1_src
    assert "download_from_hf(HF_REFERENCE_BUNDLE_PATH)" in cell1_src

    # Verify Cell 2 downloads missing blobs / falls back to ollama pull, and strips HF tokens
    assert 'download_from_hf(f"{HF_OLLAMA_BLOBS_PREFIX}/sha256-{expected_sha}")' in cell2_src
    assert '"ollama", "pull", "ornith-1.5:9b"' in cell2_src or '[OLLAMA_BIN, "pull", "ornith-1.5:9b"]' in cell2_src
    assert 'os.environ.pop(_tok_key, None)' in cell2_src

    # Verify Cell 3 strips HF tokens from OpenCode/run_python subprocess environment
    assert 'for _tok_key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_HUB_TOKEN"):' in cell3_src
    assert 'env.pop(_tok_key, None)' in cell3_src


def test_smoke_two_final_answers_are_verified_against_python_result() -> None:
    ns = _load_cell3_normalizer_namespace()
    cell4 = ast.parse("".join(_load_notebook_cells()[4]["source"]))
    diagnose = next(
        node for node in cell4.body
        if isinstance(node, ast.FunctionDef) and node.name == "diagnose_smoke_stage"
    )
    exec(compile(ast.Module(body=[diagnose], type_ignores=[]), str(NOTEBOOK_PATH), "exec"), ns)

    qid = "q_8f16268d281c"
    expected = {"id": qid, "type": "number", "answer": 21563000}
    raw_final = (
        'Đoạn kết quả đã xác nhận.\n\n**Trả lời:** `"21563000"`\n\n'
        'Trong ngày 14/04/2026 có 165 dòng "Đã hoàn thành" và 5 dòng "Huỷ đơn"; '
        'loại 5 đơn huỷ → tổng doanh thu = **21.563.000 VNĐ** (đã bao gồm phí phục vụ phòng lạnh).'
    )
    python_result = {
        "tool": "run_python",
        "status": "completed",
        "full_result": {
            "success": True,
            "kind": "final",
            "parsed_output": {"kind": "final", "type": "number", "answer": 21563000, "evidence": "sum(Amount)"},
        },
    }
    normalize = ns["normalize_final_answer"]
    normalized = normalize(qid, raw_final, [python_result])
    assert normalized["prediction"] == expected
    assert normalized["type_source"] == "tool:run_python"
    trace = {**normalized, "tool_calls": [python_result]}
    assert ns["diagnose_smoke_stage"](trace, "number", 21563000)[0]

    empty_after_python = normalize(qid, "", [python_result])
    assert empty_after_python["prediction"] == expected
    assert empty_after_python["type_source"] == "tool:run_python"
    assert empty_after_python["abstain_reason"] is None

    wrong_final = raw_final.replace('"21563000"', '"1"') + "\nTool tính ra 21563000."
    assert normalize(qid, wrong_final, [python_result])["abstain_reason"] == "unparseable_final"
    assert normalize(qid, raw_final, [])["abstain_reason"] == "unparseable_final"
    observation = {
        **python_result,
        "full_result": {"success": True, "kind": "observation", "parsed_output": {"kind": "observation", "data": 21563000}},
    }
    missing_final = normalize(qid, "21563000", [observation])
    assert missing_final["prediction"]["type"] == "abstain"
    assert missing_final["tool_rescue_prediction"] is None
    assert normalize(qid, "", [observation])["prediction"]["type"] == "abstain"
    trace_without_final = {**missing_final, "tool_calls": [observation]}
    ok, diagnostic = ns["diagnose_smoke_stage"](trace_without_final, "number", 21563000)
    assert not ok and "chưa ra kết quả hợp lệ" in diagnostic


def test_unparseable_final_hardening_and_dual_gpu_worker_config() -> None:
    ns = _load_cell3_normalizer_namespace()
    normalize_final = ns["normalize_final_answer"]

    agg_41 = [
        {
            "tool": "aggregate",
            "status": "completed",
            "messageID": "msg_tool",
            "full_result": {"type": "number", "answer": 41},
        }
    ]

    # 1. <think>...</think> before bare number 41 -> normalized via tool:aggregate
    r_think_bare = normalize_final("q1", "<think>\nĐếm được 41 phiếu.\n</think>\n41", agg_41)
    assert r_think_bare["prediction"] == {"id": "q1", "type": "number", "answer": 41}
    assert r_think_bare["type_source"] == "tool:aggregate"

    # 2. <think>...</think> before explicit JSON
    r_think_json = normalize_final("q2", '<think>ok</think>\n{"type": "number", "answer": 41}', agg_41)
    assert r_think_json["prediction"] == {"id": "q2", "type": "number", "answer": 41}
    assert r_think_json["type_source"] == "model"

    # 3. Nested JSON object (table) inside prose
    r_nested = normalize_final("q3", 'Kết quả là {"type": "table", "answer": {"columns": ["A"], "rows": [[1]]}}.', [])
    assert r_nested["prediction"] == {"id": "q3", "type": "table", "answer": {"columns": ["A"], "rows": [[1]]}}
    assert r_nested["type_source"] == "model"

    # 4. Markdown bold / trailing dot / short unit prose matching verified tool result
    for text_variant in ("**41**", "`41`", "41.", "41 đơn hàng", "Ngày 2025-03-28 có 41 đơn hợp lệ."):
        res = normalize_final("q4", text_variant, agg_41)
        assert res["prediction"] == {"id": "q4", "type": "number", "answer": 41}, (text_variant, res)
        assert res["type_source"] == "tool:aggregate"

    # 5. Refusal/abstention prose must STILL abstain, never rescue
    r_refusal = normalize_final("q5", "Không đủ dữ liệu để xác định chắc chắn (tạm tính 41).", agg_41)
    assert r_refusal["prediction"] == {"id": "q5", "type": "abstain", "answer": None}
    assert r_refusal["abstain_reason"] == "unparseable_final"

    # 6. Ambiguous multi-number prose must STILL abstain
    r_multi = normalize_final("q6", "Có 12 đơn A và 41 đơn B.", agg_41)
    assert r_multi["prediction"] == {"id": "q6", "type": "abstain", "answer": None}
    assert r_multi["abstain_reason"] == "unparseable_final"

    # 7. Prose without matching verified tool must STILL abstain
    r_no_tool = normalize_final("q7", "41 đơn hàng", [])
    assert r_no_tool["prediction"] == {"id": "q7", "type": "abstain", "answer": None}
    assert r_no_tool["abstain_reason"] == "unparseable_final"

    # 8. Verify one Ollama request and a 16K context per GPU, plus dual-worker diagnostics.
    cells = _load_notebook_cells()
    cell1_src = "".join(cells[1]["source"])
    cell2_src = "".join(cells[2]["source"])
    cell3_src = "".join(cells[3]["source"])
    cell4_src = "".join(cells[4]["source"])
    assert 'OLLAMA_KEEP_ALIVE' in cell2_src
    assert 'OLLAMA_NUM_PARALLEL"] = str(PARALLEL_SLOTS_PER_GPU)' in cell2_src
    assert '"num_ctx": NUM_CTX' in cell2_src
    assert 'CUDA_VISIBLE_DEVICES' in cell2_src
    assert 'PARALLEL_SLOTS_PER_GPU = 1' in cell1_src
    assert 'NUM_CTX = 65536' in cell1_src
    assert 'MAX_OUTPUT_TOKENS = 4096' in cell1_src
    assert 'NUM_BATCH = 128' in cell1_src
    assert 'MAX_STEPS = 10' in cell1_src
    assert 'RUN_PYTHON_TIMEOUT_SEC = 90' in cell1_src
    assert 'OPENCODE_TOOL_TIMEOUT_MS = 180000' in cell1_src
    assert 'PER_QUESTION_TIMEOUT_SEC = 600' in cell1_src
    assert 'MAX_STEPS_EVAL_AGENT = 14' in cell1_src
    assert 'TOOL_MAX_BYTES_EVAL_AGENT = 8000' in cell1_src
    assert '"limit": {"context": NUM_CTX, "output": MAX_OUTPUT_TOKENS}' in cell3_src
    assert '[str(RULEBOOK_PATH), str(sys_instr_path)]' in cell3_src
    assert 'dual_w0.json' in cell4_src
    assert 'dual_w1.json' in cell4_src
    assert 'print_smoke_failure_details("DUAL_W1"' in cell4_src

    # 9. OpenCode step-limit apology containing unanswerable/JSON without verified tool must still abstain as step_limit_reached
    r_step_limit = normalize_final(
        "q_step",
        'Do not invoke any tools.\n\nThe maximum number of steps has been reached.\n{"type": "unanswerable", "answer": null}',
        [],
    )
    assert r_step_limit["prediction"] == {"id": "q_step", "type": "abstain", "answer": None}
    assert r_step_limit["abstain_reason"] == "step_limit_reached"

    # 10. OpenCode step-limit summary AFTER verified aggregate=41 resolves via tool:aggregate instead of discarding computed answer
    r_step_with_tool = normalize_final(
        "q_step_ok",
        'Do not invoke any tools.\n\nThe maximum number of steps has been reached.\n\nSummary: computed count = 41.',
        agg_41,
    )
    assert r_step_with_tool["prediction"] == {"id": "q_step_ok", "type": "number", "answer": 41}
    assert r_step_with_tool["type_source"] == "tool:aggregate"

    r_step_with_tool_no_num = normalize_final(
        "q_step_nonum",
        'Do not invoke any tools.\n\nThe maximum number of steps permitted for completing this task has been reached.\nSummary of work completed (steps 1, 2, 3).',
        agg_41,
    )
    assert r_step_with_tool_no_num["prediction"] == {"id": "q_step_nonum", "type": "number", "answer": 41}
    assert r_step_with_tool_no_num["type_source"] == "tool:aggregate"


def test_bridge_stringified_null_and_xlsx_fast_inspect(tmp_path: Path) -> None:
    # 1. Stringified "None"/"null" on CSV must return schema, not ColumnNotFound: None
    biz_125_dir = REPO_ROOT / "data" / "train" / "data" / "biz_125"
    env_125 = {
        **os.environ,
        "DATAMATE_DATA_ROOT": str(biz_125_dir.resolve()),
        "DATAMATE_SRC_ROOT": str(STRUCTURED_DIR.resolve()),
        "DATAMATE_WORK_DIR": str(tmp_path / "work_125"),
        "DATAMATE_AS_OF_DATE": "2025-03-28",
        "DATAMATE_RULEBOOK_PATH": str((REPO_ROOT / "data" / "train" / "rulebook.md").resolve()),
        "DATAMATE_CALENDAR_PATH": str((REPO_ROOT / "data" / "train" / "calendar.csv").resolve()),
    }
    res_null_str = json.loads(
        subprocess.run(
            [sys.executable, str(BRIDGE_PATH), "inspect_table", json.dumps({"file": "ban_hang.csv", "column": "None"})],
            env=env_125, capture_output=True, text=True, encoding="utf-8", check=True, timeout=30,
        ).stdout.strip()
    )
    assert "columns" in res_null_str and "error" not in res_null_str

    # 2. run_python plain print() error includes actionable protocol reminder
    res_proto = json.loads(
        subprocess.run(
            [sys.executable, str(BRIDGE_PATH), "run_python", json.dumps({"code": "print(123)"})],
            env=env_125, capture_output=True, text=True, encoding="utf-8", check=True, timeout=30,
        ).stdout.strip()
    )
    assert res_proto["success"] is False
    assert res_proto["error_kind"] == "protocol_violation"
    assert "emit_obs" in res_proto["error"] and "emit_final" in res_proto["error"]

    # 3. XLSX-only shop (biz_112) must surface other_files and support fast sheet peek without 20s timeout
    biz_112_dir = REPO_ROOT / "data" / "train" / "data" / "biz_112"
    env_112 = {
        **env_125,
        "DATAMATE_DATA_ROOT": str(biz_112_dir.resolve()),
        "DATAMATE_WORK_DIR": str(tmp_path / "work_112"),
    }
    res_list = json.loads(
        subprocess.run(
            [sys.executable, str(BRIDGE_PATH), "inspect_table", json.dumps({"file": None, "column": None})],
            env=env_112, capture_output=True, text=True, encoding="utf-8", check=True, timeout=30,
        ).stdout.strip()
    )
    other_names = [x["file"] for x in res_list.get("other_files", [])]
    assert "So_chi_tiet_ban_hang_2026.xlsx" in other_names

    res_xlsx = json.loads(
        subprocess.run(
            [sys.executable, str(BRIDGE_PATH), "inspect_table", json.dumps({"file": "So_chi_tiet_ban_hang_2026.xlsx", "column": "null"})],
            env=env_112, capture_output=True, text=True, encoding="utf-8", check=True, timeout=15,
        ).stdout.strip()
    )
    assert res_xlsx.get("type") == "xlsx"
    assert "T06_2026" in res_xlsx.get("sheets", [])


def test_question_timeout_keeps_byte_encoded_opencode_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ns = _load_cell3_normalizer_namespace()
    ns.update(
        BASE_MODEL_TAG="test",
        NUM_CTX=16384,
        MAX_OUTPUT_TOKENS=2048,
        MAX_STEPS=10,
        TOOL_MAX_BYTES=1000,
        STRUCTURED_SRC_ROOT=STRUCTURED_DIR,
        RULEBOOK_PATH=REPO_ROOT / "data" / "train" / "rulebook.md",
        RULEBOOK_SHA256="fixture",
        CALENDAR_PATH=None,
        RUN_PYTHON_TIMEOUT_SEC=90,
        OPENCODE_TOOL_TIMEOUT_MS=180000,
        OPENCODE_BIN="opencode",
        PER_QUESTION_TIMEOUT_SEC=600,
    )
    question = ns["QuestionItem"]("q_test", "biz_test", "Số đơn hôm nay?", "2025-03-28")
    shop = tmp_path / "split" / "data" / question.business_id
    shop.mkdir(parents=True)
    (shop / "README.md").write_text("fixture", encoding="utf-8")
    events = [
        {"type": "tool_use", "part": {"tool": "aggregate", "state": {
            "status": "completed", "output": '{"type":"number","answer":41}',
        }}},
        {"type": "text", "part": {"messageID": "partial", "text": "41"}},
        {"type": "step_finish", "part": {"messageID": "partial", "reason": "tool-calls"}},
    ]

    def time_out(cmd, **kwargs):
        stdout = "\n".join(json.dumps(event) for event in events).encode("utf-8")
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"], output=stdout, stderr="còn log".encode("utf-8"))

    monkeypatch.setattr(subprocess, "run", time_out)
    trace = ns["run_single_question"](question, tmp_path / "split", tmp_path / "out", "structured_only", 0.0, "test")
    assert trace["timed_out"]
    assert trace["tool_calls"][0]["tool"] == "aggregate"
    assert trace["finish_reason"] == "tool-calls"
    assert trace["stderr"] == "còn log"
    assert trace["prediction"]["type"] == "abstain"
    assert trace["abstain_reason"] == "question_timeout"

    events[0]["part"] = {
        "tool": "run_python",
        "state": {
            "status": "completed",
            "output": json.dumps({
                "success": True,
                "kind": "final",
                "parsed_output": {"kind": "final", "type": "number", "answer": 41, "evidence": "counted"},
            }),
        },
    }
    ns.update(MAX_STEPS_EVAL_AGENT=14, TOOL_MAX_BYTES_EVAL_AGENT=8000)
    trace = ns["run_single_question"](question, tmp_path / "split", tmp_path / "out_python", "eval_agent", 0.0, "test")
    assert trace["timed_out"]
    assert trace["prediction"] == {"id": question.id, "type": "number", "answer": 41}
    assert trace["abstain_reason"] is None


@pytest.mark.parametrize("python_final", [True, False])
def test_eval_agent_retries_finalization_in_same_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, python_final: bool
) -> None:
    ns = _load_cell3_normalizer_namespace()
    ns.update(
        BASE_MODEL_TAG="test", NUM_CTX=65536, MAX_OUTPUT_TOKENS=4096,
        MAX_STEPS=10, MAX_STEPS_EVAL_AGENT=14, TOOL_MAX_BYTES=1000, TOOL_MAX_BYTES_EVAL_AGENT=8000,
        STRUCTURED_SRC_ROOT=STRUCTURED_DIR, RULEBOOK_PATH=REPO_ROOT / "data" / "train" / "rulebook.md",
        RULEBOOK_SHA256="fixture", CALENDAR_PATH=None, RUN_PYTHON_TIMEOUT_SEC=90,
        OPENCODE_TOOL_TIMEOUT_MS=180000, OPENCODE_BIN="opencode", PER_QUESTION_TIMEOUT_SEC=600,
    )
    question = ns["QuestionItem"]("q_test", "biz_test", "Giá bán bao nhiêu?", "2025-12-01")
    shop = tmp_path / "split" / "data" / question.business_id
    shop.mkdir(parents=True)
    attempts = []

    def fake_run(cmd, **kwargs):
        attempts.append(cmd)
        if len(attempts) == 1:
            payload = {"success": False, "kind": "error", "error_kind": "protocol_violation", "error": "plain print"}
            answer_text = "Ngày 01/12/2025 tìm được đơn giá 37000. Đã hết bước."
        else:
            assert len(attempts) == 2
            assert cmd[-3:-1] == ["--session", "ses_fixture"]
            assert "emit_final" in cmd[-1] and "37000" not in cmd[-1]
            recovery_config = json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])
            assert recovery_config["permission"] == {"*": "deny", "run_python": "allow"}
            assert recovery_config["agent"]["build"]["steps"] == 3
            assert kwargs["timeout"] <= 120
            if python_final:
                payload = {
                    "success": True, "kind": "final",
                    "parsed_output": {"kind": "final", "type": "number", "answer": 37000, "evidence": "sheet row"},
                }
                answer_text = ""
            else:
                payload = {"success": True, "kind": "observation", "parsed_output": {"kind": "observation", "data": 37000}}
                answer_text = '{"type":"number","answer":37000}'
        mid = f"m{len(attempts)}"
        events = [
            {"type": "tool_use", "sessionID": "ses_fixture", "part": {
                "tool": "run_python", "messageID": mid, "state": {"status": "completed", "output": json.dumps(payload)},
            }},
            {"type": "text", "sessionID": "ses_fixture", "part": {"messageID": mid, "text": answer_text}},
            {"type": "step_finish", "sessionID": "ses_fixture", "part": {"messageID": mid, "reason": "stop"}},
        ]
        stdout = "\n".join(json.dumps(event) for event in events)
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    trace = ns["run_single_question"](question, tmp_path / "split", tmp_path / "out", "eval_agent", 0.0, "test")
    assert trace["finalization_retry_attempted"]
    assert len(trace["tool_calls"]) == len(attempts) == 2
    if python_final:
        assert trace["prediction"] == {"id": question.id, "type": "number", "answer": 37000}
        assert trace["type_source"] == "tool:run_python"
    else:
        assert trace["prediction"]["type"] == "abstain"


def test_biz_112_mojibake_and_header_offset_resilience(tmp_path: Path) -> None:
    biz_112_dir = REPO_ROOT / "data" / "train" / "data" / "biz_112"
    env = {
        **os.environ,
        "DATAMATE_DATA_ROOT": str(biz_112_dir.resolve()),
        "DATAMATE_SRC_ROOT": str(STRUCTURED_DIR.resolve()),
        "DATAMATE_WORK_DIR": str(tmp_path / "work_112"),
        "DATAMATE_AS_OF_DATE": "2026-07-31",
        "DATAMATE_RULEBOOK_PATH": str((REPO_ROOT / "data" / "train" / "rulebook.md").resolve()),
        "DATAMATE_CALENDAR_PATH": str((REPO_ROOT / "data" / "train" / "calendar.csv").resolve()),
    }

    def invoke(action: str, payload: dict) -> dict:
        proc = subprocess.run(
            [sys.executable, str(BRIDGE_PATH), action, json.dumps(payload, ensure_ascii=False)],
            env=env, capture_output=True, text=True, encoding="utf-8", check=True, timeout=30,
        )
        return json.loads(proc.stdout.strip())

    # 1. inspect_table(file=None) surfaces sheets and mojibake alias
    res_list = invoke("inspect_table", {"file": None, "column": None})
    by_name = {item["file"]: item for item in res_list.get("other_files", [])}
    assert "T12_2025" in by_name["So_chi_tiet_ban_hang_1.xlsx"].get("sheets", [])
    assert "T06_2026" in by_name["So_chi_tiet_ban_hang_2026.xlsx"].get("sheets", [])
    mojibake_entry = next(v for v in by_name.values() if v.get("alias") == "Danh sách hàng hóa.xlsx")
    assert mojibake_entry["sheets"] == ["Sheet1"]

    # 2. inspect_table resolves CP437 mojibake filename with and without extension
    res_menu_ext = invoke("inspect_table", {"file": "Danh sách hàng hóa.xlsx", "column": None})
    assert res_menu_ext.get("type") == "xlsx"
    assert "Tên hàng hóa" in res_menu_ext["sheets_preview"]["Sheet1"]["columns"]
    res_menu_stem = invoke("inspect_table", {"file": "Danh sách hàng hóa", "column": None})
    assert res_menu_stem.get("sheets") == ["Sheet1"]

    # 3. _fast_inspect_xlsx preserves 0-based header_row_index=3 (empty row 2 not stripped out of index calculation)
    res_sales1 = invoke("inspect_table", {"file": "So_chi_tiet_ban_hang_1.xlsx", "column": None})
    assert res_sales1["sheets_preview"]["T12_2025"]["header_row_index"] == 3

    # 4. pd.read_excel(..., sheet_name="T12_2025", header=2) auto-repairs header and computes 37000
    py_header2 = invoke(
        "run_python",
        {
            "code": (
                'df = pd.read_excel("So_chi_tiet_ban_hang_1.xlsx", sheet_name="T12_2025", header=2)\n'
                'assert "Tên hàng hóa" in df.columns and "Đơn giá" in df.columns\n'
                'm = df[(df["Ngày"].astype(str).str.contains("01/12/2025", na=False)) & '
                '(df["Tên hàng hóa"].astype(str) == "Soda chanh dây (M)")]\n'
                'price = int(round(float(parse_vn_number(m["Đơn giá"].iloc[0]))))\n'
                'emit_final(price, type="number", evidence="T12_2025 header=2 repaired")'
            )
        },
    )
    assert py_header2["success"] is True and py_header2["parsed_output"]["answer"] == 37000

    # 5. Cross-file sheet fallback with header=2 on So_chi_tiet_ban_hang_2026.xlsx also finds T12_2025 -> 37000
    py_cross = invoke(
        "run_python",
        {
            "code": (
                'df = pd.read_excel("So_chi_tiet_ban_hang_2026.xlsx", sheet_name="T12_2025", header=2)\n'
                'm = df[(df["Ngày"].astype(str).str.contains("01/12/2025", na=False)) & '
                '(df["Tên hàng hóa"].astype(str) == "Soda chanh dây (M)")]\n'
                'price = int(round(float(parse_vn_number(m["Đơn giá"].iloc[0]))))\n'
                'emit_final(price, type="number", evidence="cross-file T12_2025")'
            )
        },
    )
    assert py_cross["success"] is True and py_cross["parsed_output"]["answer"] == 37000

    # 6. openpyxl.load_workbook("Danh sách hàng hóa.xlsx") and pd.read_excel(..., sheet_name=None).sheet_names succeed
    py_openpyxl_and_dict = invoke(
        "run_python",
        {
            "code": (
                'import openpyxl\n'
                'wb = openpyxl.load_workbook("Danh sách hàng hóa.xlsx", read_only=True)\n'
                'wb_sheets = list(wb.sheetnames)\n'
                'wb.close()\n'
                'xl = pd.read_excel("So_chi_tiet_ban_hang_2026.xlsx", sheet_name=None)\n'
                'dict_sheets = list(xl.sheet_names)\n'
                'emit_obs({"wb_sheets": wb_sheets, "dict_sheets": dict_sheets}, "verified")'
            )
        },
    )
    assert py_openpyxl_and_dict["success"] is True
    assert py_openpyxl_and_dict["parsed_output"]["data"]["wb_sheets"] == ["Sheet1"]
    assert py_openpyxl_and_dict["parsed_output"]["data"]["dict_sheets"] == ["T06_2026", "T07_2026"]

    # 7. prepare_isolated_shop_root copies ONLY repaired UTF-8 filename (no CP437 mojibake duplicate, 0o444)
    ns = _load_cell3_normalizer_namespace()
    q_112 = ns["QuestionItem"]("q_01a28f2233bd", "biz_112", "gia ban soda?", "2026-07-31")
    root_base = tmp_path / "iso_112"
    shop_root = ns["prepare_isolated_shop_root"](q_112, REPO_ROOT / "data" / "train", root_base)
    try:
        assert sorted(p.name for p in shop_root.iterdir()) == [
            "Danh sách hàng hóa.xlsx",
            "README.md",
            "So_chi_tiet_ban_hang_1.xlsx",
            "So_chi_tiet_ban_hang_2026.xlsx",
        ]
        sys_inst = ns["build_system_instructions"](tool_mode="eval_agent", shop_root=shop_root)
        assert "Danh sách file dữ liệu trong shop:" in sys_inst
        assert "README.md" not in sys_inst.split("Danh sách file dữ liệu trong shop:", 1)[1].split("]", 1)[0]
        assert sys_inst.index("Bước 1") < sys_inst.index("Bước 2") < sys_inst.index("Bước 3")
        assert str(shop_root / "README.md") in sys_inst
    finally:
        ns["_remove_readonly_tree"](root_base)

    # 8. inspect_table(file="README.md") returns README text and deduplicated file list
    res_readme = invoke("inspect_table", {"file": "README.md", "column": None})
    assert "readme" in res_readme and "biz_112" in res_readme["readme"]
    assert len(res_readme.get("other_files", [])) >= 3

    # 9. ShopExplorer alias + auto-emit observation + pd.read_excel().sheetnames + &sheet= + str.contains fallback + protocol_violation order
    py_resilience = invoke(
        "run_python",
        {
            "code": (
                'wb_df = pd.read_excel("So_chi_tiet_ban_hang_1.xlsx")\n'
                'sheets = list(wb_df.sheetnames)\n'
                'df_q = pd.read_excel("So_chi_tiet_ban_hang_1.xlsx&sheet=T12_2025")\n'
                'day_mask = df_q["Ngày"].astype(str).str.contains("01/12/2025", na=False)\n'
                'm1 = df_q[day_mask & df_q["Tên hàng hóa"].str.contains("Soda chanh dây (M)", na=False, case=False)]\n'
                'm2 = df_q[day_mask & df_q["Tên hàng hóa"].str.contains(r"Soda chanh dây \\(M\\)", regex=False, case=False)]\n'
                'm3 = df_q[day_mask & df_q["Tên hàng hóa"].str.contains("soda chanh", regex=False, na=False)]\n'
                'p1 = int(round(float(parse_vn_number(m1["Đơn giá"].iloc[0]))))\n'
                'p2 = int(round(float(parse_vn_number(m2["Đơn giá"].iloc[0]))))\n'
                'has_m3 = "Soda chanh dây (M)" in m3["Tên hàng hóa"].astype(str).tolist()\n'
                'emit_obs({"sheets": sheets, "p1": p1, "p2": p2, "has_m3": has_m3}, "resilience ok")\n'
            )
        },
    )
    assert py_resilience["success"] is True
    res_data = py_resilience["parsed_output"]["data"]
    assert "T12_2025" in res_data["sheets"] and len(res_data["sheets"]) >= 12
    assert res_data["p1"] == 37000 and res_data["p2"] == 37000 and res_data["has_m3"] is True

    py_shop_explorer = invoke(
        "run_python",
        {
            "code": (
                'from ShopExplorer import explore_data, load_clean_df\n'
                'explore_data("Danh sách hàng hóa.xlsx")\n'
            )
        },
    )
    assert py_shop_explorer["success"] is True
    assert py_shop_explorer["parsed_output"]["kind"] == "observation"

    py_proto = invoke("run_python", {"code": 'print("debug_marker_123")'})
    assert py_proto["success"] is False and py_proto["error_kind"] == "protocol_violation"
    assert py_proto["error"].startswith("(Protocol reminder:")
    assert py_proto["error"].index("(Protocol reminder:") < py_proto["error"].index("Protocol violation:")

    # 10. Trace regression: openclaw_kernels_helpers, emit_final() 0-arg fallback + stdout bound, duplicate answer kwarg
    py_openclaw = invoke(
        "run_python",
        {"code": 'from openclaw_kernels_helpers import emit_obs\nemit_obs(None, "listed")'},
    )
    assert py_openclaw["success"] is True and py_openclaw["parsed_output"]["kind"] == "observation"

    py_empty_final = invoke(
        "run_python",
        {"code": 'print("HEADER_MARK")\nprint("X" * 20000)\nprint("TAIL_MARK")\nemit_final()'},
    )
    assert py_empty_final["success"] is True and py_empty_final["parsed_output"]["kind"] == "observation"
    assert "HEADER_MARK" in py_empty_final["stdout"] and "TAIL_MARK" in py_empty_final["stdout"]
    assert "truncated" in py_empty_final["stdout"]
    assert len(json.dumps(py_empty_final, ensure_ascii=False)) <= 9200

    py_dup_ans = invoke(
        "run_python",
        {"code": 'emit_final("done", type="string", answer="done")'},
    )
    assert py_dup_ans["success"] is True and py_dup_ans["parsed_output"]["answer"] == "done"

    py_msg_kw = invoke(
        "run_python",
        {"code": 'emit_final(parse_vn_number("37,000.0000"), type="number", msg="extra msg", evidence="row 26")'},
    )
    assert py_msg_kw["success"] is True
    assert py_msg_kw["parsed_output"]["kind"] == "final"
    assert py_msg_kw["parsed_output"]["answer"] == 37000
    assert py_msg_kw["parsed_output"]["evidence"] == "row 26"






def _run_python_final(type_: str, answer) -> dict:
    return {
        "tool": "run_python",
        "status": "completed",
        "full_result": {
            "success": True,
            "kind": "final",
            "parsed_output": {"kind": "final", "type": type_, "answer": answer, "evidence": "x", **({"reason": "thiếu dữ liệu"} if type_ == "unanswerable" else {})},
        },
    }


def test_unparseable_final_rescues_consistent_unanswerable_date_string_only() -> None:
    normalize = _load_cell3_normalizer_namespace()["normalize_final_answer"]

    # unanswerable đã emit_final: prose kể lý do không bị coi là mâu thuẫn
    r = normalize("q1", "Trả lời được không — shop không lưu dữ liệu tồn kho.", [_run_python_final("unanswerable", None)])
    assert r["prediction"] == {"id": "q1", "type": "unanswerable", "answer": None}
    assert r["abstain_reason"] is None

    # date: prose dd/mm/yyyy cùng ngày với kết quả đã xác minh
    r = normalize("q2", "30/07/2026", [_run_python_final("date", "2026-07-30")])
    assert r["prediction"] == {"id": "q2", "type": "date", "answer": "2026-07-30"}
    r = normalize("q2b", "Ngày 29/07/2026 là cao nhất.", [_run_python_final("date", "2026-07-30")])
    assert r["abstain_reason"] == "unparseable_final"

    # string: chỉ một cụm in đậm và đúng bằng kết quả
    tool = [_run_python_final("string", "Snack Oishi tôm cay 40g")]
    r = normalize("q3", "The answer is **Snack Oishi tôm cay 40g** (966 đơn vị).", tool)
    assert r["prediction"]["answer"] == "Snack Oishi tôm cay 40g"
    r = normalize("q3b", "The answer is **Mì Hảo Hảo** not **Snack Oishi tôm cay 40g**.", tool)
    assert r["abstain_reason"] == "unparseable_final"

    # final kiểu string nhét dict/JSON không được coi là kết quả đã xác minh, và không lùi về final cũ
    wrapped = _run_python_final("string", '{"type": "string", "answer": "Cty Tăng Giang"}')
    r = normalize("q4", "", [_run_python_final("number", 68972200), wrapped])
    assert r["prediction"]["type"] == "abstain"
    assert r["tool_rescue_prediction"] is None


def test_month_string_final_is_coerced_to_date_yyyy_mm() -> None:
    normalize = _load_cell3_normalizer_namespace()["normalize_final_answer"]
    for raw, want in (("8/2025", "2025-08"), ("tháng 9/2025", "2025-09"), ("12-2024", "2024-12"), ("2025-08", "2025-08"), ("2025/9", "2025-09")):
        r = normalize("q1", "", [_run_python_final("string", raw)])
        assert r["prediction"] == {"id": "q1", "type": "date", "answer": want}, raw
    r = normalize("q2", "", [_run_python_final("string", "13/2025")])   # không phải tháng hợp lệ: giữ nguyên string
    assert r["prediction"]["type"] == "string"
