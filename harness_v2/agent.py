"""Vòng lặp agent tối thiểu. Điểm khác OpenCode: kiểm soát từng lượt gọi model.
- giới hạn token mỗi lượt; lượt bị cắt (finish=length) không bị bỏ cuộc mà được nhắc viết ngắn rồi thử lại;
- đáp án lấy thẳng từ emit_final của tool, không phụ thuộc vào việc model có viết lại đúng định dạng hay không."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from harness_v2.catalog import build_catalog
from harness_v2.llm import LLMError
from harness_v2.tools import SCHEMAS, ToolBox

SYSTEM = """Bạn trả lời câu hỏi tiếng Việt về dữ liệu của một shop. Dữ liệu nằm trong các file của shop (CSV, XLSX, SQLite); bạn chỉ có các tool được cấp.

Quy trình:
1. Đọc rulebook bên dưới và áp dụng đúng nó. Đọc README của shop (tool read) để biết cách ghi dữ liệu riêng của shop.
2. Xem cấu trúc file cần dùng (inspect_table, explore_data) trước khi tính; mở đủ các file liên quan.
3. Tính bằng run_python (dùng print để xem kết quả). Khi đã kiểm tra điều kiện lọc, kỳ thời gian và dòng tổng, CHỐT bằng tool emit_final(answer, type, evidence) — đây là một tool riêng, không gọi trong run_python.
4. Suy luận NGẮN. Mỗi lượt phải kết thúc bằng một lệnh gọi tool. Khi phân vân, chọn cách hiểu theo rulebook rồi kiểm tra bằng dữ liệu thật.
5. Nếu dữ liệu không đủ hoặc câu hỏi không xác định được duy nhất một đáp án, chốt đúng theo mục tương ứng của rulebook.

=== RULEBOOK ===
{rulebook}"""

USER = "{question}\n\nas_of_date: {as_of}\nCác file dữ liệu của shop: {files}"
CATALOG = ("\n\nMục lục dữ liệu (tự động quét, chỉ mô tả cấu trúc; KHÔNG phải quy tắc tính, quy tắc lấy từ rulebook và README). "
           "Dùng đúng tên file, sheet, bảng và cột ở đây, đừng đoán:\n{catalog}")
CHALLENGE = ("CHƯA CHỐT. Các nguồn dữ liệu sau chưa được dùng trong phép tính: {files}. Với từng nguồn, xác định theo README và rulebook "
             "xem nó có thuộc phạm vi chỉ tiêu của câu hỏi không (nguồn gốc của số liệu, sổ ngoài hệ thống, sổ riêng cho loại giao dịch, "
             "danh mục tra cứu...). Nếu có thì kiểm tra rồi tính lại; nếu không thì gọi lại emit_final với cùng đáp án.")
REVIEW = ("Kiểm tra lần cuối trước khi chốt: (1) Câu hỏi có xác định được DUY NHẤT một đối tượng, kỳ và chỉ tiêu không? Nếu có nhiều ứng viên cùng khớp "
          "(vd trùng tên) mà câu hỏi không phân biệt, hoặc dữ liệu không có, thì xem mục tương ứng của rulebook về cách chốt thay vì chọn một. "
          "(2) Đã áp dụng đủ các mục rulebook và README liên quan (trạng thái, kỳ, cách ghi dữ liệu, nguồn số liệu) chưa? "
          "Nếu đã chắc thì gọi lại emit_final; nếu chưa thì kiểm tra rồi chốt.")
NUDGE_TRUNC = ("Lượt trước bị cắt vì suy luận quá dài. Suy luận tối đa vài câu rồi gọi ngay tool tiếp theo.")
NUDGE_NOFINAL = "Chưa có kết quả chốt. Hãy tính bằng run_python rồi gọi tool emit_final(answer, type, evidence)."


@dataclass
class Config:
    max_steps: int = 20            # số lượt gọi model
    max_tokens: int = 4096         # token tối đa mỗi lượt
    timeout: float = 600           # giây cho cả câu
    max_truncations: int = 3
    max_nudges: int = 2
    max_challenges: int = 1        # số lần chặn đáp án để yêu cầu kiểm tra lại (nguồn chưa dùng, rà soát cuối)
    review: bool = False           # chặn MỌI đáp án một lần để rà soát cuối (đối tượng duy nhất, rulebook)
    catalog: bool = True           # đưa mục lục dữ liệu vào đầu hội thoại
    extra_body: dict = field(default_factory=dict)


def _family(name: str) -> str:
    """Họ file: bỏ phần số/ngày/dấu, vd Order.all.20250601_20250630.xlsx -> orderall (các file theo tháng cùng một họ)."""
    return re.sub(r"[\d_.\-\s]+", "", Path(name).stem).lower() or name.lower()


def unused_sources(files: list[str], used_blob: str) -> list[str]:
    """Đại diện (một tên file) cho mỗi họ file chưa xuất hiện trong code/tham số tính toán."""
    blob = used_blob.lower()
    def used(f: str) -> bool:   # tên file, tên không đuôi, hoặc tiền tố trước phần số (code hay dùng glob như "Order.all.*")
        stem = Path(f).stem.lower()
        prefix = re.split(r"\d", stem)[0]
        return f.lower() in blob or stem in blob or (len(prefix) >= 4 and prefix in blob)
    touched = {_family(f) for f in files if used(f)}
    seen, out = set(), []
    for f in files:
        fam = _family(f)
        if fam not in touched and fam not in seen:
            seen.add(fam)
            out.append(f)
    return out


def _json_args(raw: str) -> dict | None:
    try:
        obj = json.loads(raw or "{}")
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _parse_text_answer(text: str) -> dict | None:
    m = re.search(r'\{[^{}]*"type"[^{}]*\}', text or "", re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return {"type": obj["type"], "answer": obj.get("answer")} if obj.get("type") == "abstain" else None


def run_agent(item: dict, split_dir: Path, llm: Callable[..., dict], cfg: Config | None = None, work_dir: Path | None = None) -> dict:
    cfg = cfg or Config()
    t0 = time.time()
    box = ToolBox(split_dir, item, work_dir)
    rulebook = (split_dir / "rulebook.md").read_text(encoding="utf-8")
    messages = [{"role": "system", "content": SYSTEM.format(rulebook=rulebook)},
                {"role": "user", "content": USER.format(question=item["question"], as_of=item["as_of_date"], files=box.files())
                 + (CATALOG.format(catalog=build_catalog(box)) if cfg.catalog else "")}]
    trace, usage = [], {"prompt": 0, "completion": 0}
    trunc = nudges = challenges = 0
    used_blob = ""   # code và tham số của các lần tính toán, để biết file nào đã được dùng
    result: dict = {"type": "abstain", "answer": None, "reason": "max_steps"}

    for step in range(cfg.max_steps):
        left = cfg.timeout - (time.time() - t0)
        if left <= 5:
            result = {"type": "abstain", "answer": None, "reason": "question_timeout"}
            break
        try:
            r = llm(messages, SCHEMAS, max_tokens=cfg.max_tokens, timeout=min(left, 300), extra_body=cfg.extra_body)
        except LLMError as exc:
            result = {"type": "abstain", "answer": None, "reason": f"llm_error:{str(exc)[:80]}"}
            break
        usage["prompt"] += r["usage"].get("prompt_tokens", 0)
        usage["completion"] += r["usage"].get("completion_tokens", 0)
        trace.append({"step": step, "finish": r["finish"], "reasoning_chars": len(r["reasoning"]), "content": r["content"][:500],
                      "calls": [(c["name"], c["arguments"][:300]) for c in r["tool_calls"]]})

        parsed = [(c, _json_args(c["arguments"])) for c in r["tool_calls"]]
        if r["finish"] == "length" and (not parsed or any(a is None for _, a in parsed)):
            trunc += 1
            if trunc > cfg.max_truncations:
                result = {"type": "abstain", "answer": None, "reason": "truncated"}
                break
            messages.append({"role": "user", "content": NUDGE_TRUNC})   # lượt bị cắt không đưa vào lịch sử
            continue

        if parsed:
            messages.append({"role": "assistant", "content": r["content"] or None, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}} for c, _ in parsed]})
            final_msgs = []
            for c, args in parsed:
                out = box.call(c["name"], args) if args is not None else json.dumps({"error": "arguments không phải JSON"})
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
                if c["name"] in ("run_python", "explore_data"):
                    used_blob += c["arguments"]
                if c["name"] == "emit_final":
                    final_msgs.append(messages[-1])
                trace[-1].setdefault("results", []).append(out[:600])   # để chẩn đoán: model thấy gì sau mỗi lần gọi tool
            if box.final:
                unused = unused_sources(box.files(), used_blob)
                if (unused or cfg.review) and challenges < cfg.max_challenges and step < cfg.max_steps - 2:
                    challenges += 1   # chưa nhận đáp án: bắt đối chiếu nguồn chưa dùng và/hoặc rà soát cuối
                    text = " ".join(([CHALLENGE.format(files=", ".join(unused))] if unused else []) + ([REVIEW] if cfg.review else []))
                    box.final = None
                    if final_msgs:
                        for m in final_msgs:
                            m["content"] = json.dumps({"ok": False, "message": text}, ensure_ascii=False)
                    else:
                        messages.append({"role": "user", "content": text})
                    trace[-1]["challenge"] = unused or ["review"]
                    continue
                result = dict(box.final)
                break
            continue

        txt = _parse_text_answer(r["content"])   # model tự chốt abstain bằng văn bản
        if txt:
            result = {**txt, "reason": "model_abstain"}
            break
        nudges += 1
        if nudges > cfg.max_nudges:
            result = {"type": "abstain", "answer": None, "reason": "no_final"}
            break
        messages += [{"role": "assistant", "content": r["content"] or "(trống)"}, {"role": "user", "content": NUDGE_NOFINAL}]

    result.update({"steps": len(trace), "truncations": trunc, "tokens": usage, "elapsed": round(time.time() - t0, 2)})
    result["trace"] = trace
    return result
