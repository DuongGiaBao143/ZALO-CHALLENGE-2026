"""Bộ tool cho agent. inspect_table, explore_data, run_python dùng lại bridge.py của harness cũ (cùng sandbox, cùng helper)
để khi so sánh với OpenCode chỉ khác phần vòng lặp; read tự viết, chỉ đọc README/rulebook trong phạm vi shop."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from harness_v2.catalog import sqlite_table_info

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "submission" / "runtime"

_NULLABLE = lambda desc: {"type": ["string", "null"], "description": desc}  # noqa: E731

SCHEMAS = [
    {"type": "function", "function": {
        "name": "read", "description": "Đọc một file văn bản của shop (README.md).",
        "parameters": {"type": "object", "properties": {"filePath": {"type": "string", "description": "Đường dẫn file"}}, "required": ["filePath"]}}},
    {"type": "function", "function": {
        "name": "inspect_table",
        "description": "Xem cấu trúc dữ liệu. file=null: liệt kê file. file=<tên>: sheet, tên cột, vài dòng đầu. file+column: các giá trị thực tế của cột.",
        "parameters": {"type": "object", "properties": {"file": _NULLABLE("Tên file trong thư mục shop"), "sheet": _NULLABLE("Tên sheet (file xlsx): chỉ xem cấu trúc sheet đó"), "column": _NULLABLE("Tên cột cần xem nhãn")}}}},
    {"type": "function", "function": {
        "name": "explore_data",
        "description": "Xem dữ liệu của file ở đúng mốc thời gian của câu hỏi, kèm số dòng theo trạng thái và các dòng Tổng kề bên (không cộng chung với dòng hàng).",
        "parameters": {"type": "object", "properties": {
            "file": {"type": "string", "description": "Tên file"}, "date": _NULLABLE("YYYY-MM-DD, YYYY-MM, dd/mm/yyyy hoặc cụm như 'hôm qua'"),
            "sheet": _NULLABLE("Tên sheet"), "column": _NULLABLE("Cột cần xem giá trị"), "keyword": _NULLABLE("Từ khoá cần tìm")}, "required": ["file"]}}},
    {"type": "function", "function": {
        "name": "run_python",
        "description": ("Chạy code Python chỉ đọc trên dữ liệu shop. Có sẵn trong globals (KHÔNG import): pd, explore_data, load_clean_df, resolve_date, "
                        "parse_vn_date, parse_vn_number, vn_num, emit_obs(data, msg) để thăm dò, emit_final(answer, type=..., evidence=...) để chốt đáp án. "
                        "Mỗi lượt phải kết thúc bằng emit_obs hoặc emit_final."),
        "parameters": {"type": "object", "properties": {"code": {"type": "string", "description": "Mã Python"}}, "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "emit_final",
        "description": ("CHỐT đáp án cuối (gọi trực tiếp như một tool, KHÔNG gọi qua run_python). Gọi sau khi đã kiểm tra bằng dữ liệu thật. "
                        "type: number | percent | string | date | boolean | list | table | unanswerable. "
                        "answer là GIÁ TRỊ thuần (số, chuỗi, danh sách...), không bọc JSON; unanswerable thì answer = null."),
        "parameters": {"type": "object", "properties": {
            "answer": {"description": "Giá trị đáp án"}, "type": {"type": "string", "description": "Kiểu đáp án"},
            "evidence": {"type": "string", "description": "Điều kiện đã áp dụng, ngắn gọn"}}, "required": ["answer", "type"]}}},
]

ANSWER_TYPES = {"number", "percent", "string", "date", "boolean", "list", "table", "unanswerable"}


def _clip(text: str, limit: int = 6000) -> str:
    return text if len(text) <= limit else text[: limit * 2 // 3] + f"\n... [cắt {len(text) - limit} ký tự] ...\n" + text[-limit // 3:]


class ToolBox:
    def __init__(self, split_dir: Path, item: dict, work_dir: Path | None = None):
        self.shop_dir = (split_dir / "data" / item["business_id"]).resolve()
        self.rulebook = split_dir / "rulebook.md"
        self.work_dir = work_dir or Path(tempfile.mkdtemp(prefix="hv2_"))
        self.env = {**os.environ, "DATAMATE_DATA_ROOT": str(self.shop_dir), "DATAMATE_SRC_ROOT": str(RUNTIME),
                    "DATAMATE_WORK_DIR": str(self.work_dir), "DATAMATE_AS_OF_DATE": item["as_of_date"],
                    "DATAMATE_RULEBOOK_PATH": str(self.rulebook), "DATAMATE_CALENDAR_PATH": str(split_dir / "calendar.csv"),
                    "DATAMATE_TIMEOUT_SEC": os.environ.get("DATAMATE_TIMEOUT_SEC", "90"),
                    "DATAMATE_AUTO_WRAP_STDOUT": "1"}   # print() không gọi emit_obs vẫn trả về cho model; thiếu thì model "mù" và lặp lại lệnh
        for k in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_HUB_TOKEN"):
            self.env.pop(k, None)   # code của model không được thấy token
        self.final: dict | None = None   # payload emit_final đầu tiên hợp lệ

    def files(self) -> list[str]:
        return sorted(p.name for p in self.shop_dir.iterdir() if p.is_file() and p.name.lower() != "readme.md")

    def call(self, name: str, args: dict) -> str:
        if name == "read":
            return self._read(str(args.get("filePath", "")))
        if name == "emit_final":
            return self._emit_final(args)
        if name not in ("inspect_table", "explore_data", "run_python"):
            return json.dumps({"error": f"tool không tồn tại: {name}"}, ensure_ascii=False)
        if name == "inspect_table" and args.get("file") and args["file"] not in self.files():
            hit = sqlite_table_info(self.shop_dir, str(args["file"]))   # model hay gọi bằng tên bảng SQLite thay vì tên file
            if hit:
                return _clip(json.dumps(hit, ensure_ascii=False))
        if name == "inspect_table" and args.get("sheet") not in (None, "", "None", "null"):
            return self._inspect_sheet(args)   # bridge không có tham số sheet, mà model hay truyền
        out = self.bridge(name, args)
        if name == "run_python":
            self._capture_final(out)
            if "ModuleNotFoundError" in out:
                out += '\n[Gợi ý] Chỉ import được thư viện có thật (pandas, numpy, openpyxl...). pd và np đã có sẵn: dùng pd.read_excel(...) không cần import.'
        return _clip(out)

    def _inspect_sheet(self, args: dict) -> str:
        """inspect_table(file, sheet): lấy phần xem trước của đúng sheet đó từ kết quả inspect_table(file) của bridge."""
        base = {k: v for k, v in args.items() if k not in ("sheet", "column")}
        try:
            info = json.loads(self.bridge("inspect_table", {**base, "column": None}))
        except json.JSONDecodeError:
            return json.dumps({"error": "không đọc được cấu trúc file"}, ensure_ascii=False)
        previews = info.get("sheets_preview") or {}
        if args["sheet"] not in previews:
            return json.dumps({"error": f"không có sheet {args['sheet']!r}", "sheets": info.get("sheets")}, ensure_ascii=False)
        return _clip(json.dumps({"file": info.get("file"), "sheet": args["sheet"], **previews[args["sheet"]]}, ensure_ascii=False))

    def bridge(self, name: str, args: dict) -> str:
        """Gọi một action của bridge.py, trả nguyên văn (không cắt); lỗi trả chuỗi JSON {"error":...}."""
        try:
            proc = subprocess.run([sys.executable, str(RUNTIME / "bridge.py"), name, json.dumps(args, ensure_ascii=False)],
                                  env=self.env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=int(self.env["DATAMATE_TIMEOUT_SEC"]) + 30)
        except subprocess.TimeoutExpired:
            return json.dumps({"error": "tool quá thời gian"}, ensure_ascii=False)
        out = (proc.stdout or "").strip()
        if proc.returncode != 0 or not out:
            return json.dumps({"error": _clip((proc.stderr or "tool lỗi").strip(), 1500)}, ensure_ascii=False)
        return out

    def _emit_final(self, args: dict) -> str:
        typ, ans = args.get("type"), args.get("answer")
        if typ not in ANSWER_TYPES:
            return json.dumps({"error": f"type phải thuộc {sorted(ANSWER_TYPES)}"}, ensure_ascii=False)
        if isinstance(ans, str) and ans.strip().startswith("{"):   # model hay bọc đáp án thành chuỗi JSON {"type":..,"answer":..}
            try:
                inner = json.loads(ans)
                if isinstance(inner, dict) and "answer" in inner:
                    ans = inner["answer"]
            except json.JSONDecodeError:
                pass
        if typ == "unanswerable":
            ans = None
        if typ == "boolean" and isinstance(ans, str):   # model hay gửi "true"/"false" dạng chuỗi
            low = ans.strip().lower()
            if low in ("true", "đúng", "yes", "có"):
                ans = True
            elif low in ("false", "sai", "no", "không"):
                ans = False
            else:
                return json.dumps({"error": f"boolean phải là true/false, nhận được {ans!r}"}, ensure_ascii=False)
        if typ in ("number", "percent") and isinstance(ans, str):   # model hay gửi số dưới dạng chuỗi "4"
            try:
                f = float(ans.replace(",", "").strip())
                ans = int(f) if f == int(f) and typ == "number" else f
            except ValueError:
                return json.dumps({"error": f"{typ} phải là số, nhận được {ans!r}"}, ensure_ascii=False)
        if self.final is None:
            self.final = {"type": typ, "answer": ans}
        return json.dumps({"ok": True, "message": "Đã chốt đáp án."}, ensure_ascii=False)

    def _capture_final(self, out: str) -> None:
        try:
            obj = json.loads(out)
        except json.JSONDecodeError:
            return
        po = obj.get("parsed_output") if isinstance(obj, dict) else None
        if isinstance(po, dict) and po.get("kind") == "final" and "answer" in po and po.get("type") and self.final is None:
            self.final = {"type": po["type"], "answer": po["answer"]}

    def _read(self, path: str) -> str:
        p = Path(path)
        p = (self.shop_dir / p) if not p.is_absolute() else p
        try:
            p = p.resolve()
            if not (p == self.rulebook.resolve() or self.shop_dir in p.parents) or p.suffix.lower() not in {".md", ".txt"}:
                return json.dumps({"error": "chỉ đọc được README.md/rulebook của shop"}, ensure_ascii=False)
            return _clip(p.read_text(encoding="utf-8", errors="replace"), 12000)
        except OSError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
