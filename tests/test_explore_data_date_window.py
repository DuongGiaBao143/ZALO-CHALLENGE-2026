"""explore_data(date=...) of the shipped runtime: rows of one date + the summary rows next to them.

Runs in a subprocess because the shipped runtime (submission/runtime) and the repo-root `src` package
share the package name `src`.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

RUNTIME = Path(__file__).resolve().parents[1] / "submission" / "runtime"

SNIPPET = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
os.chdir(sys.argv[2]); os.environ["BUSINESS_DIR"] = os.getcwd()
import src.agent.sandbox as sb
sb.BUSINESS_DIR = os.getcwd()
kw = json.loads(sys.argv[3])
print(json.dumps(sb.explore_data("ban.xlsx", **kw), ensure_ascii=False, default=str))
"""


@pytest.fixture()
def shop(tmp_path):
    serial = lambda y, m, d: (pd.Timestamp(y, m, d) - pd.Timestamp(1899, 12, 30)).days
    rows = []
    for day, amounts in [((2025, 7, 2), [4000, 236400]), ((2026, 7, 1), [3773100]), ((2026, 7, 2), [2000000, 3495500])]:
        for i, a in enumerate(amounts):
            rows.append({"Trạng thái": "Đã hoàn thành", "Tổng tiền": f"{a:,}", "ngay_ban": serial(*day), "Nội dung": f"Hàng {i}"})
        rows.append({"Trạng thái": None, "Tổng tiền": f"{sum(amounts):,}", "ngay_ban": None, "Nội dung": f"Tổng ngày {day[2]:02d}/{day[1]:02d}"})
    pd.DataFrame(rows).to_excel(tmp_path / "ban.xlsx", index=False)
    return tmp_path


def explore(shop, **kw):
    out = subprocess.run([sys.executable, "-c", SNIPPET, str(RUNTIME), str(shop), json.dumps(kw)],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_iso_day_returns_rows_and_the_matching_total_row(shop):
    r = explore(shop, date="2026-07-02")
    assert r["rows_in_window"] == 2 and r["date_column"] == "ngay_ban"
    near = r["summary_rows_near_window"]
    assert [x["Tổng tiền"] for x in near if x["Nội dung"] == "Tổng ngày 02/07"] == ["5,495,500"]
    assert any("gấp đôi" in n for n in r["notes"])


def test_relative_phrase_uses_as_of_date(shop):
    r = explore(shop, date="hôm qua", as_of_date="2026-07-03")
    assert r["window"] == ["2026-07-02", "2026-07-02"] and r["rows_in_window"] == 2


def test_empty_window_and_unreadable_date(shop):
    assert explore(shop, date="2030-01-01")["rows_in_window"] == 0
    assert explore(shop, date="blah blah")["error"].startswith("DateNotUnderstood")


def test_overview_without_date_is_unchanged(shop):
    r = explore(shop)
    assert "date_coverage" in r and "rows_in_window" not in r


def run_tool(shop, args, as_of="2026-07-03"):
    """The explore_data OpenCode tool end to end: bridge.py -> sandbox, as_of_date from the harness env."""
    import os
    env = {**os.environ, "DATAMATE_SRC_ROOT": str(RUNTIME), "DATAMATE_DATA_ROOT": str(shop),
           "DATAMATE_AS_OF_DATE": as_of, "DATAMATE_WORK_DIR": __import__("tempfile").mkdtemp(), "DATAMATE_TIMEOUT_SEC": "60"}
    out = subprocess.run([sys.executable, str(RUNTIME / "bridge.py"), "explore_data", json.dumps(args)],
                         capture_output=True, text=True, timeout=180, env=env)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_tool_relative_date_gets_as_of_from_env_not_from_model(shop):
    r = run_tool(shop, {"file": "ban.xlsx", "date": "hôm qua", "sheet": None, "column": None, "keyword": None})
    assert r["success"] is True
    d = r["parsed_output"]["data"]
    # the bridge forward-fills empty dates: the total row must still be recognised and kept out of the item rows
    assert d["window"] == ["2026-07-02", "2026-07-02"] and d["rows_in_window"] == 2
    assert [x["Tổng tiền"] for x in d["summary_rows_near_window"] if x["Nội dung"] == "Tổng ngày 02/07"] == ["5,495,500"]


def test_tool_rejects_unknown_args_and_missing_file(shop):
    assert "error" in run_tool(shop, {"file": "ban.xlsx", "as_of_date": "2000-01-01"})
    assert "error" in run_tool(shop, {"date": "2026-07-02"})
