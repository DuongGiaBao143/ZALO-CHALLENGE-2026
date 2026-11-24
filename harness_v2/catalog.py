"""Mục lục dữ liệu của shop, sinh tự động bằng code (không dùng model): file, sheet/bảng, cột, vài giá trị mẫu.
Chỉ mô tả CẤU TRÚC; không chứa quy tắc nghiệp vụ (quy tắc vẫn lấy từ rulebook và README)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SQLITE_EXT = {".sqlite", ".sqlite3", ".db"}


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)   # chỉ đọc


def sqlite_tables(path: Path) -> dict[str, dict]:
    """tên bảng -> {rows, columns:[(tên, kiểu)], sample: dòng đầu}"""
    out: dict[str, dict] = {}
    try:
        con = _connect(path)
        for (t,) in con.execute("select name from sqlite_master where type in ('table','view') and name not like 'sqlite_%' order by name").fetchall():
            cols = [(c[1], c[2] or "") for c in con.execute(f'PRAGMA table_info("{t}")').fetchall()]
            n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
            row = con.execute(f'select * from "{t}" limit 1').fetchone()
            out[t] = {"rows": n, "columns": cols, "sample": list(row) if row else []}
        con.close()
    except sqlite3.Error:
        pass
    return out


def sqlite_table_info(shop_dir: Path, table: str) -> dict | None:
    """Nếu `table` là tên bảng trong một file SQLite của shop thì trả cấu trúc của nó, ngược lại None."""
    for p in sorted(shop_dir.iterdir()):
        if p.suffix.lower() in SQLITE_EXT:
            t = sqlite_tables(p).get(table)
            if t:
                return {"file": p.name, "table": table, "rows": t["rows"], "columns": [{"name": n, "type": ty} for n, ty in t["columns"]],
                        "sample_row": dict(zip([n for n, _ in t["columns"]], t["sample"]))}
    return None


def _short(v, n: int = 40) -> str:
    s = repr(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def _sqlite_lines(p: Path) -> list[str]:
    lines = [f"- {p.name} (SQLite). Truy vấn bằng sqlite3 trong run_python; DÙNG ĐÚNG tên cột dưới đây:"]
    for t, info in sqlite_tables(p).items():
        cols = ", ".join(f"{n}" + (f" {ty}" if ty else "") for n, ty in info["columns"])
        lines.append(f"  - {t} ({info['rows']} dòng): {cols}")
        if info["sample"]:
            lines.append("      dòng mẫu: " + ", ".join(_short(v) for v in info["sample"][:12]))
    return lines


def _sheet_cols(sp: dict) -> list[str]:
    """Bridge đoán dòng tiêu đề có thể rơi vào khối tiêu đề sổ: lấy dòng đầu tiên có nhiều ô chữ nhất trong các dòng đầu."""
    rows = [r for r in (sp.get("first_rows") or []) if isinstance(r, list)]
    if rows:
        cnt = [len([c for c in r if str(c).strip()]) for r in rows]
        return list(dict.fromkeys(str(c) for c in rows[cnt.index(max(cnt))] if str(c).strip()))[:24]
    return list(dict.fromkeys(str(c) for c in (sp.get("columns") or [])))[:24]


def _table_lines(box, name: str) -> list[str]:
    try:
        info = json.loads(box.bridge("inspect_table", {"file": name, "column": None}))
    except json.JSONDecodeError:
        return [f"- {name}"]
    previews = info.get("sheets_preview")
    if not isinstance(previews, dict) or not previews:
        cols = [str(c) for c in (info.get("columns") or [])][:30]
        return [f"- {name} | cột: {', '.join(cols)}" if cols else f"- {name}"]
    groups: dict = {}
    for sname, sp in previews.items():
        groups.setdefault(tuple(_sheet_cols(sp or {})), []).append(sname)
    lines = []
    for cols, names in groups.items():
        shown = ", ".join(f'"{n}"' for n in names[:4]) + (f" (+{len(names) - 4} sheet cùng cột)" if len(names) > 4 else "")
        lines.append(f"- {name} | sheet {shown}" + (f" | cột: {', '.join(cols)}" if cols else ""))
    return lines


def build_catalog(box, max_chars: int = 7000) -> str:
    lines: list[str] = []
    n_tab = 0
    for name in box.files():
        p = box.shop_dir / name
        try:
            if p.suffix.lower() in SQLITE_EXT:
                lines += _sqlite_lines(p)
            elif p.suffix.lower() in {".csv", ".xlsx", ".xls"} and n_tab < 12:
                n_tab += 1
                lines += _table_lines(box, name)
            else:
                lines.append(f"- {name}")
        except Exception:   # mục lục chỉ là gợi ý: một file lỗi không được làm hỏng câu hỏi
            lines.append(f"- {name}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0] + "\n- ... (còn nữa; xem bằng inspect_table)"
    return text
