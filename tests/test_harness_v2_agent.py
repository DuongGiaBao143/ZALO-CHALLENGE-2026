from pathlib import Path

from harness_v2.agent import Config, run_agent
from harness_v2.evalsets import ROOT, load_jsonl

SPLIT = ROOT / "data" / "private_test" / "private_test"
ITEM = next(q for q in load_jsonl(SPLIT / "questions.jsonl") if q["id"] == "q_05fff802a476")


def scripted(responses):
    seen = []

    def llm(messages, tools, *, max_tokens, timeout, extra_body):
        seen.append(list(messages))
        return responses[len(seen) - 1]
    llm.seen = seen
    return llm


def reply(calls=(), content="", finish="tool_calls"):
    return {"content": content, "reasoning": "", "finish": finish, "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "tool_calls": [{"id": f"c{i}", "name": n, "arguments": a} for i, (n, a) in enumerate(calls)]}


def test_truncated_turn_is_retried_and_final_comes_from_tool():
    final_code = '{"code": "emit_final(42, type=\'number\', evidence=\'t\')"}'
    llm = scripted([reply(finish="length"), reply([("run_python", final_code)])])
    res = run_agent(ITEM, SPLIT, llm, Config(max_challenges=0))
    assert (res["type"], res["answer"]) == ("number", 42)
    assert res["truncations"] == 1 and res["steps"] == 2
    assert "bị cắt" in llm.seen[1][-1]["content"]   # nhắc viết ngắn, lượt bị cắt không nằm trong lịch sử


def test_gives_up_after_repeated_truncation_and_missing_final():
    res = run_agent(ITEM, SPLIT, scripted([reply(finish="length")] * 6), Config(max_truncations=2))
    assert res["type"] == "abstain" and res["reason"] == "truncated"
    res = run_agent(ITEM, SPLIT, scripted([reply(content="42", finish="stop")] * 6), Config(max_nudges=1))
    assert res["reason"] == "no_final"


def test_read_is_limited_to_shop_files(tmp_path):
    from harness_v2.tools import ToolBox
    box = ToolBox(SPLIT, ITEM, tmp_path)
    assert "Quy ước" in box.call("read", {"filePath": "README.md"})
    assert "error" in box.call("read", {"filePath": str(SPLIT / "answer.jsonl")})


def test_emit_final_is_a_real_tool_and_unwraps_json_string():
    call = ("emit_final", '{"answer": "{\\"type\\": \\"number\\", \\"answer\\": 7}", "type": "number", "evidence": "t"}')
    res = run_agent(ITEM, SPLIT, scripted([reply([call])]), Config(max_challenges=0))
    assert (res["type"], res["answer"]) == ("number", 7)


def test_emit_final_rejects_bad_type_and_unanswerable_has_no_answer():
    from harness_v2.tools import ToolBox
    box = ToolBox(SPLIT, ITEM)
    assert "error" in box.call("emit_final", {"answer": 1, "type": "int"}) and box.final is None
    box.call("emit_final", {"answer": 5, "type": "unanswerable"})
    assert box.final == {"type": "unanswerable", "answer": None}


def test_import_pd_error_gets_a_hint():
    from harness_v2.tools import ToolBox
    out = ToolBox(SPLIT, ITEM).call("run_python", {"code": "import pd"})
    assert "pd và np đã có sẵn" in out


def test_numeric_string_answer_is_coerced():
    from harness_v2.tools import ToolBox
    box = ToolBox(SPLIT, ITEM)
    box.call("emit_final", {"answer": "4", "type": "number"})
    assert box.final == {"type": "number", "answer": 4} and isinstance(box.final["answer"], int)
    box2 = ToolBox(SPLIT, ITEM)
    assert "error" in box2.call("emit_final", {"answer": "abc", "type": "percent"})


def test_catalog_lists_sqlite_columns_and_inspect_accepts_table_names():
    from harness_v2.catalog import build_catalog
    from harness_v2.tools import ToolBox
    item = next(q for q in load_jsonl(SPLIT / "questions.jsonl") if q["business_id"] == "pvt_006")
    box = ToolBox(SPLIT, item)
    cat = build_catalog(box)
    assert "nv_nhapkho" in cat and "ma_ncc" in cat and "BangKeHoaDon.xlsx" in cat
    info = box.call("inspect_table", {"file": "nv_nhapkho"})
    assert "so_phieu_nhap" in info and "error" not in info


def test_unused_source_families_and_boolean_coercion():
    from harness_v2.agent import unused_sources
    files = ["Order.all.20250601_20250630.xlsx", "Order.all.20250701_20250731.xlsx", "SoDonNgoaiSan.xlsx", "pos.sqlite"]
    assert unused_sources(files, 'pd.read_excel("Order.all.20250601_20250630.xlsx")') == ["SoDonNgoaiSan.xlsx", "pos.sqlite"]
    assert unused_sources(files, "SoDonNgoaiSan pos.sqlite glob('Order.all.*')") == []
    from harness_v2.tools import ToolBox
    box = ToolBox(SPLIT, ITEM)
    box.call("emit_final", {"answer": "false", "type": "boolean"})
    assert box.final == {"type": "boolean", "answer": False}


def test_final_is_challenged_once_when_a_data_source_is_unused():
    ok = [("emit_final", '{"answer": 5, "type": "number"}')]
    llm = scripted([reply(ok), reply(ok)])
    res = run_agent(ITEM, SPLIT, llm, Config())
    assert (res["type"], res["answer"]) == ("number", 5) and res["steps"] == 2
    assert res["trace"][0]["challenge"]   # lần đầu bị chặn vì chưa dùng file nào
    assert any("CHƯA CHỐT" in str(m.get("content")) for m in llm.seen[1])
    res = run_agent(ITEM, SPLIT, scripted([reply(ok)]), Config(max_challenges=0))   # tắt chặn: nhận ngay
    assert res["steps"] == 1


def test_inspect_table_accepts_sheet_argument():
    from harness_v2.tools import ToolBox
    out = ToolBox(SPLIT, ITEM).call("inspect_table", {"file": "SoDiem_7A2.xlsx", "sheet": "DS lớp"})
    assert "HO VA TEN" in out and "error" not in out
    bad = ToolBox(SPLIT, ITEM).call("inspect_table", {"file": "SoDiem_7A2.xlsx", "sheet": "không có"})
    assert "không có sheet" in bad


def test_review_challenges_every_final_once():
    ok = [("emit_final", '{"answer": 5, "type": "number"}')]
    llm = scripted([reply(ok), reply(ok)])
    res = run_agent(ITEM, SPLIT, llm, Config(review=True, max_challenges=1))
    assert res["steps"] == 2 and any("Kiểm tra lần cuối" in str(m.get("content")) for m in llm.seen[1])
