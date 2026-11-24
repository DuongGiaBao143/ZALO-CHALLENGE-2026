"""Agent runner: OpenCode 1.19.5 + Ollama + Ornith 1.5 9B, one question end-to-end.

Everything below the CONFIG block is copied from CELL 3 of
notebooks/Evaluate_Ornith_OpenCode_Kaggle_2T4.ipynb (the code that was evaluated),
with three small changes: (1) the parser also returns reasoning/text messages for
the required logs, (2) run_single_question takes a per-call timeout so a global
time budget can be enforced across threads, (3) the notebook-only loader was removed.
"""
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ----------------------------------------------------------------------------- CONFIG
RUNTIME_DIR = Path(os.environ.get("DATAMATE_RUNTIME_DIR", "/code/runtime"))
OPENCODE_RUNTIME_DIR = RUNTIME_DIR
STRUCTURED_SRC_ROOT = RUNTIME_DIR
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from src.agent.sandbox import validate_protocol_payload  # noqa: E402
from src.schemas import AnswerType, QuestionItem, SubmissionItem, VALID_ANSWER_TYPES  # noqa: E402

SPLIT_DIR = Path(os.environ.get("DATAMATE_SPLIT_DIR", "/data"))
RULEBOOK_PATH = SPLIT_DIR / "rulebook.md"
CALENDAR_PATH = (SPLIT_DIR / "calendar.csv") if (SPLIT_DIR / "calendar.csv").is_file() else None
RULEBOOK_SHA256 = hashlib.sha256(RULEBOOK_PATH.read_bytes()).hexdigest() if RULEBOOK_PATH.is_file() else ""

_nm = Path(os.environ.get("DATAMATE_NODE_MODULES", "/opt/opencode_node_modules"))
PRE_STAGED_NODE_MODULES = _nm if _nm.is_dir() else None
OPENCODE_BIN = shutil.which("opencode") or "opencode"

BASE_MODEL_TAG = "ornith15-datamate-pilot-8k:latest"
NUM_CTX = int(os.environ.get("DATAMATE_NUM_CTX", "65536"))
SEED = 42
NUM_BATCH = 128
PRESENCE_PENALTY = 0
MAX_OUTPUT_TOKENS = 4096
MAX_STEPS = 10
MAX_STEPS_EVAL_AGENT = 14
TOOL_MAX_BYTES = 1000
TOOL_MAX_BYTES_EVAL_AGENT = 8000
RUN_PYTHON_TIMEOUT_SEC = 90
OPENCODE_TOOL_TIMEOUT_MS = 180000
PER_QUESTION_TIMEOUT_SEC = int(os.environ.get("DATAMATE_PER_QUESTION_TIMEOUT_SEC", "600"))

# ----------------------------------------------------------------------------- COPIED FROM NOTEBOOK CELL 3
import math
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

ALLOWED_SHOP_EXTENSIONS = {".csv", ".xlsx", ".xls", ".sqlite", ".db", ".sqlite3"}


def _remove_readonly_tree(target: Path) -> None:
    if not target.exists():
        return
    for root, dirs, files in os.walk(target):
        for d in dirs:
            try:
                os.chmod(Path(root) / d, 0o755)
            except OSError:
                pass
        for f in files:
            try:
                os.chmod(Path(root) / f, 0o644)
            except OSError:
                pass
    shutil.rmtree(target)


def prepare_isolated_shop_root(question_item: QuestionItem, split_dir: Path, root_base: Path) -> Path:
    """Copy dữ liệu shop vào shop root riêng (không dùng symlink để không trượt guard resolve() của bridge.py)."""
    src_shop = split_dir / "data" / question_item.business_id
    if not src_shop.is_dir():
        raise FileNotFoundError(f"Không thấy thư mục shop {src_shop}")

    shop_root = root_base / question_item.id / "data"
    _remove_readonly_tree(shop_root.parent)
    shop_root.mkdir(parents=True, exist_ok=True)

    for entry in sorted(src_shop.iterdir()):
        if entry.is_file() and (entry.suffix.lower() in ALLOWED_SHOP_EXTENSIONS or entry.name.lower() == "readme.md"):
            try:
                repaired = entry.name.encode("cp437").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                repaired = ""
            target_name = (
                repaired
                if repaired and repaired != entry.name and Path(repaired).name == repaired and not (src_shop / repaired).exists()
                else entry.name
            )
            dst = shop_root / target_name
            if not dst.exists():
                shutil.copy2(entry, dst)
                os.chmod(dst, 0o444)
    return shop_root


def build_system_instructions(shop_root: Path, tool_mode: str) -> str:
    """Tạo system instructions khớp mục 2 của handoff, thay /data bằng shop_root thực tế."""
    if tool_mode == "eval_agent":
        available_files = (
            sorted(p.name for p in shop_root.iterdir() if p.is_file() and p.name.lower() != "readme.md")
            if shop_root.exists()
            else []
        )
        readme_path = shop_root / "README.md"
        files_hint = f" Danh sách file dữ liệu trong shop: {available_files}." if available_files else ""
        return (
            f"Dữ liệu shop nằm trong `{shop_root}`.{files_hint}\n"
            "QUY TRÌNH BẮT BUỘC (thực hiện ĐÚNG THỨ TỰ từng bước, KHÔNG nhảy cóc vào `run_python` khi chưa xong Bước 1 và Bước 2):\n"
            f"- Bước 1 — ĐỌC THÔNG TIN SHOP & RULEBOOK TRƯỚC: Trước khi viết code hay tính toán, đọc kỹ rulebook ở trên trong system prompt để xác định định nghĩa chỉ tiêu, quy ước làm tròn, loại trừ đơn hủy/trả và kiểu `type` cần trả; đồng thời gọi tool `read` với `filePath=\"{readme_path}\"` để nắm quy ước riêng của shop, ý nghĩa từng file và từng cột.\n"
            "- Bước 2 — XEM BẢNG & SHEET BẰNG `inspect_table`: Gọi `inspect_table(file=None, column=None)` và `inspect_table(file='<ten_file>', column=None)` cho MỌI file trong danh sách (không bỏ file nào, kể cả file tên khó hiểu như sổ quỹ, phiếu thu chi: công nợ, thanh toán, giá, tồn thường nằm ở file riêng; chưa mở hết thì không được kết luận là thiếu dữ liệu) để biết chính xác danh sách sheet (chọn ĐÚNG sheet khớp tháng/năm của câu hỏi, không đọc nhầm sheet khác), tên cột, và nhãn `Trạng thái` thực tế.\n"
            "- Bước 3 — XEM DỮ LIỆU Ở ĐÚNG MỐC THỜI GIAN CỦA CÂU HỎI BẰNG TOOL `explore_data` (bắt buộc với câu có ngày/tuần/tháng/quý hoặc cụm như \'hôm qua\', \'tháng này\'): gọi tool `explore_data(file=\'<ten_file>\', date=\'<mốc>\')` (không cần viết code; thêm `sheet=\'<ten_sheet>\'` nếu file nhiều sheet). `date` nhận \'YYYY-MM-DD\', \'YYYY-MM\', \'dd/mm/yyyy\' hoặc nguyên cụm như \'hôm qua\'. Đọc `date_column`, `rows_in_window`, `status_counts_in_window`, `sample_rows`, đặc biệt `summary_rows_near_window` và `notes`: đó là dòng tổng/cộng do chủ shop ghi sẵn (ngày trống, nội dung \'Tổng ...\'). TUYỆT ĐỐI không cộng chúng chung với dòng hàng, nếu không kết quả bị gấp đôi; chỉ tính trên dòng hàng thật.\n"
            "- Bước 4 — TÍNH TOÁN & CHỐT ĐÁP ÁN:\n"
            "  + Nếu chỉ cần đếm `count_distinct` trên một file CSV đơn giản: dùng `aggregate`.\n"
            "  + Với mọi câu hỏi còn lại (tra giá, lọc nhiều điều kiện, tổng/trung bình/tỷ lệ, lập bảng/danh sách, nối nhiều bảng, đọc `.xlsx`/`.sqlite`): dùng `run_python`.\n"
            "Quy tắc BẮT BUỘC khi gọi `run_python`:\n"
            "  (1) KHÔNG hardcode `/data/...`; truyền tên file tương đối cho `pd.read_excel`, `pd.read_csv`, `load_clean_df('ten_file', dedup_order=False)` (không truyền `parse_dates`), hoặc `explore_data('ten_file')`.\n"
            "  (2) Lọc ngày theo `resolve_date(expr, as_of_date=AS_OF_DATE)` + `parse_vn_date(series)` và chuẩn hóa mọi giá/tiền bằng `parse_vn_number(val)` (KHÔNG dùng `int()`/`float()` trực tiếp lên chuỗi `'37,000.0000'`); nếu rulebook loại đơn hủy/trả thì loại toàn bộ các dòng thuộc các mã đơn có trạng thái đó.\n"
            "  (3) Các helper `explore_data`, `load_clean_df`, `resolve_date`, `parse_vn_date`, `parse_vn_number`, `vn_num`, `emit_obs`, `emit_final` ĐÃ CÓ SẴN trong globals (KHÔNG import). Mọi lượt `run_python` PHẢI kết thúc bằng `emit_obs(data, msg)` khi thăm dò hoặc `emit_final(answer, type=\"number\", evidence=\"...\")` khi chốt (`type` đặt trong ngoặc kép hoặc dùng identifier `number`/`string`/`boolean`/`table`/`list`, KHÔNG gọi `emit_final()` rỗng).\n"
            "  (4) Với file XLSX nhiều sheet, mở ĐÚNG sheet khớp mốc thời gian trong câu hỏi (ví dụ ngày 01/12/2025 -> sheet `T12_2025`) và dùng `usecols` nếu file lớn.\n"
            "  (5) Chỉ chốt đáp án cuối sau khi `run_python` trả `kind=final` (hoặc `aggregate` hợp lệ). Sau khi gọi `emit_final` thành công, BẮT BUỘC phải xuất đáp án cuối cùng trong câu trả lời (trả đúng giá trị JSON của `answer` ví dụ `42`, bỏ giải thích). Nếu chưa xác minh được thì trả {\"type\":\"abstain\",\"answer\":null}.\n"
            "  (6) TRƯỚC KHI CHỐT: trong cùng lượt code, kiểm tra lại điều kiện đã áp dụng (kỳ thời gian, trạng thái, dòng tổng, số dòng trước/sau mỗi bộ lọc), đối chiếu từng mục liên quan của rulebook (kể cả mục cách ghi dữ liệu trong file) và so bậc độ lớn với một kỳ liền kề cùng loại; nếu đáp án lệch bất thường (ví dụ gấp nhiều lần kỳ liền kề) thì `emit_obs` để điều tra thay vì `emit_final`. Ghi các điều kiện đã áp dụng vào `evidence`.\n"
            "  (7) KHÔNG sa vào suy nghĩ dài: khi phân vân định nghĩa, chọn định nghĩa theo rulebook rồi chạy code kiểm tra bằng dữ liệu thật; mỗi lượt suy luận phải kết thúc bằng một lệnh gọi tool hoặc đáp án.\n"
        )

    readme_hint = f"Đọc {shop_root / 'README.md'} để hiểu quy ước của shop. "
    answer_hint = "Trả đúng một JSON có hai trường type và answer từ kết quả tool. "
    return (
        f"Tuân thủ rulebook của split và dùng as_of_date từ đầu vào. "
        f"Dùng inspect_table để xác nhận cột và nhãn thực tế dùng khi lọc. "
        f"Dùng aggregate để tính dựa trên các cột, ngày và quy tắc vừa xác định. "
        f"{answer_hint}"
        f'Nếu chưa xác minh được, trả {{"type":"abstain","answer":null}}. '
        f"Dữ liệu nằm trong {shop_root}. "
        f"{readme_hint}"
        f"Gọi inspect_table với file và column đều là null để tìm bảng, rồi đọc nhãn từ cột trạng thái."
    )


def build_user_prompt(question_item: QuestionItem, shop_root: Path, tool_mode: str) -> str:
    prompt = f"{question_item.question}\n\nas_of_date: {question_item.as_of_date}"
    if tool_mode == "auto_readme_schema":
        readme = (shop_root / "README.md").read_text(encoding="utf-8") if (shop_root / "README.md").is_file() else ""
        prompt += f"\n\nREADME của shop:\n{readme}"
    return prompt


def setup_opencode_session_dir(session_dir: Path, tool_mode: str) -> Path:
    """Chuẩn bị OPENCODE_CONFIG_DIR chứa tools/, run.js và node_modules pre-staged (nếu có)."""
    if session_dir.exists():
        shutil.rmtree(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    tools_dst = session_dir / "tools"
    tools_dst.mkdir(parents=True, exist_ok=True)

    run_js_dst = session_dir / "run.js"
    shutil.copy2(OPENCODE_RUNTIME_DIR / "run.js", run_js_dst)

    allowed_tools = ["inspect_table.js", "aggregate.js"]
    if tool_mode == "eval_agent":
        allowed_tools += ["run_python.js", "explore_data.js"]
    for fname in allowed_tools:
        shutil.copy2(OPENCODE_RUNTIME_DIR / "tools" / fname, tools_dst / fname)

    if PRE_STAGED_NODE_MODULES and PRE_STAGED_NODE_MODULES.is_dir():
        nm_dst = session_dir / "node_modules"
        try:
            nm_dst.symlink_to(PRE_STAGED_NODE_MODULES.resolve())
        except OSError:
            shutil.copytree(PRE_STAGED_NODE_MODULES, nm_dst)
    return session_dir


def parse_opencode_jsonl_events(stdout_text: str, sidecar_traces: list | None = None) -> dict:
    """Tách raw_final_text theo messageID phản hồi cuối, tool_calls, tokens, finish_reason và errors."""
    events = []
    parse_errors = []
    for line in stdout_text.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            events.append(json.loads(s))
        except json.JSONDecodeError as exc:
            parse_errors.append({"line": s[:300], "error": str(exc)})

    step_starts = []
    step_finishes = []
    text_parts = []
    reasoning_parts = []
    tool_calls = []
    api_errors = []

    for ev in events:
        etype = ev.get("type")
        part = ev.get("part") if isinstance(ev.get("part"), dict) else {}
        if etype == "step_start":
            step_starts.append(part)
        elif etype == "step_finish":
            step_finishes.append(part)
        elif etype == "text":
            text_parts.append(part)
        elif etype == "reasoning":
            reasoning_parts.append(part)
        elif etype == "tool_use":
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            tool_calls.append({
                "tool": part.get("tool"),
                "callID": part.get("callID"),
                "messageID": part.get("messageID"),
                "status": state.get("status"),
                "input": state.get("input"),
                "output": state.get("output"),
                "error": state.get("error"),
                "metadata": state.get("metadata"),
                "time": state.get("time"),
            })
        elif etype == "error":
            api_errors.append(ev)

    if sidecar_traces:
        sc_idx = 0
        for tc in tool_calls:
            tname = tc.get("tool")
            if tname not in ("inspect_table", "aggregate", "run_python", "explore_data"):
                continue
            for j in range(sc_idx, len(sidecar_traces)):
                sc = sidecar_traces[j]
                if sc.get("action") == tname and (sc.get("args") == tc.get("input") or tc.get("input") is None):
                    tc["full_result"] = sc.get("result")
                    sc_idx = j + 1
                    break
            else:
                for j in range(sc_idx, len(sidecar_traces)):
                    sc = sidecar_traces[j]
                    if sc.get("action") == tname:
                        tc["full_result"] = sc.get("result")
                        sc_idx = j + 1
                        break

    final_message_id = None
    finish_reason = None
    if step_finishes:
        last_fin = step_finishes[-1]
        final_message_id = last_fin.get("messageID")
        finish_reason = last_fin.get("reason")
    elif step_starts:
        final_message_id = step_starts[-1].get("messageID")
    elif text_parts:
        final_message_id = text_parts[-1].get("messageID")

    if final_message_id is not None:
        raw_final_text = "".join(
            str(p.get("text", ""))
            for p in text_parts
            if p.get("messageID") == final_message_id
        ).strip()
    else:
        raw_final_text = ""

    token_summary = {"input": 0, "output": 0, "reasoning": 0, "total": 0,
                     "steps": len(step_finishes), "max_step_input": 0, "step_inputs": []}
    for sf in step_finishes:
        tok = sf.get("tokens") or {}
        for k in ("input", "output", "reasoning", "total"):
            if isinstance(tok.get(k), (int, float)):
                token_summary[k] += int(tok[k])
        if isinstance(tok.get("input"), (int, float)):
            n_in = int(tok["input"])
            cache = tok.get("cache") or {}
            if isinstance(cache, dict):  # count cached prompt tokens too: they still occupy context
                n_in += int(cache.get("read", 0) or 0) + int(cache.get("write", 0) or 0)
            token_summary["step_inputs"].append(n_in)
            token_summary["max_step_input"] = max(token_summary["max_step_input"], n_in)

    return {
        "session_id": next((ev["sessionID"] for ev in events if ev.get("sessionID")), None),
        "raw_final_text": raw_final_text,
        "final_message_id": final_message_id,
        "finish_reason": finish_reason,
        "tool_calls": tool_calls,
        "token_summary": token_summary,
        "api_errors": api_errors,
        "jsonl_parse_errors": parse_errors,
        "event_count": len(events),
        "reasoning_texts": [str(p.get("text", "")) for p in reasoning_parts if p.get("text")],
        "text_messages": [str(p.get("text", "")) for p in text_parts if p.get("text")],
    }


def _strip_thinking_blocks(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL | re.IGNORECASE)
    if "</think>" in cleaned.lower():
        parts = re.split(r"</think>", cleaned, flags=re.IGNORECASE)
        cleaned = parts[-1]
    return cleaned.strip()


def _strip_markdown_scalar_wrappers(text: str) -> str:
    s = (text or "").strip()
    if len(s) >= 2 and s[0] == "`" and s[-1] == "`":
        s = s[1:-1].strip()
    if len(s) >= 4 and s.startswith("**") and s.endswith("**"):
        s = s[2:-2].strip()
    elif len(s) >= 2 and s.startswith("*") and s.endswith("*"):
        s = s[1:-1].strip()
    s = re.sub(r"\s*\.$", "", s).strip()
    if len(s) >= 2 and s[0] == "`" and s[-1] == "`":
        s = s[1:-1].strip()
    return s


def _try_parse_json_candidates(text: str):
    cleaned = _strip_thinking_blocks(text)
    if not cleaned:
        return []
    candidates = []
    try:
        candidates.append(json.loads(cleaned))
    except json.JSONDecodeError:
        pass
    for m in re.finditer(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE):
        try:
            candidates.append(json.loads(m.group(1).strip()))
        except json.JSONDecodeError:
            pass
    # Scan top-level JSON objects/arrays in cleaned using JSONDecoder (handles nested JSON safely)
    decoder = json.JSONDecoder()
    decoded_blocks = []
    idx = 0
    n = len(cleaned)
    while idx < n:
        ch = cleaned[idx]
        if ch in "{[":
            try:
                obj, end_idx = decoder.raw_decode(cleaned, idx)
                decoded_blocks.append(obj)
                idx = end_idx
                continue
            except json.JSONDecodeError:
                pass
        idx += 1
    for obj in reversed(decoded_blocks):
        candidates.append(obj)
    if not candidates:
        unwrapped = _strip_markdown_scalar_wrappers(cleaned)
        if unwrapped and unwrapped != cleaned:
            try:
                candidates.append(json.loads(unwrapped))
            except json.JSONDecodeError:
                pass
    return candidates


_ABSTAIN_CUE_RE = re.compile(
    r"(?:\babstain\b|không\s*thể|không\s*đủ|thiếu\s*dữ\s*liệu|không\s*xác\s*định|chưa\s*xác\s*minh|\bcannot\b|\bunable\s+to\b|\binsufficient\b)",
    flags=re.IGNORECASE,
)


_STEP_LIMIT_PREFIX_RE = re.compile(
    r"^\s*(?:Do not invoke any tools\.\s*)?(?:The maximum number of steps[^.\n]*\.\s*(?:No further tool calls[^.\n]*\.\s*)?(?:This constraint takes priority[^.\n]*\.\s*)?|I can no longer use tools[^.\n]*\.\s*|---\s*)*",
    flags=re.IGNORECASE,
)


def _strip_step_limit_header(text: str) -> str:
    cleaned = _strip_thinking_blocks(text)
    cleaned = re.sub(
        r"(?im)^\s*(?:Do not invoke any tools\.|The maximum number of steps[^\n]*|I can no longer use tools[^\n]*|No further tool calls will be made\.[^\n]*|\*\*Báo cáo tiến độ\s*-\s*Đã đạt số bước cực đại\*\*)\s*$",
        "",
        cleaned,
    )
    cleaned = _STEP_LIMIT_PREFIX_RE.sub("", cleaned).strip()
    return cleaned


def _extract_verified_scalar_from_prose(text: str, verified_results: list[dict], max_len: int = 400):
    """Chỉ tách scalar khi text gọn, không có dấu hiệu abstain, không mơ hồ và khớp kết quả tool đã xác minh."""
    if not verified_results:
        return False, None
    cleaned = _strip_step_limit_header(text)
    if not cleaned or len(cleaned) > max_len or _ABSTAIN_CUE_RE.search(cleaned):
        return False, None

    answer_lines = re.findall(
        r"^[ \t]*(?:\*\*)?(?:trả[ \t]+lời|đáp[ \t]*án|kết[ \t]*quả|answer|result)(?:\*\*)?[ \t]*[:\-](?:\*\*)?[ \t]*([^\r\n]*)",
        cleaned,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if answer_lines:
        if len(answer_lines) != 1:
            return False, None
        cleaned = _strip_markdown_scalar_wrappers(answer_lines[0])

    # Loại chuỗi ngày ISO YYYY-MM-DD trước khi đếm số để tránh coi ngày là số xung đột
    no_dates = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", cleaned)
    raw_nums = re.findall(r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?(?![A-Za-z0-9_])", no_dates)
    num_vals = []
    for tok in raw_nums:
        try:
            val = float(tok) if "." in tok else int(tok)
            if val not in num_vals:
                num_vals.append(val)
        except ValueError:
            pass
    if len(num_vals) == 1:
        v = num_vals[0]
        if any(_values_match(v, r["answer"]) for r in verified_results):
            return True, v

    cand_str = _strip_markdown_scalar_wrappers(cleaned)
    if cand_str and any(isinstance(r["answer"], str) and _values_match(cand_str, r["answer"]) for r in verified_results):
        return True, cand_str
    return False, None


def _values_match(a, b) -> bool:
    if type(a) is bool or type(b) is bool:
        return type(a) is bool and type(b) is bool and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(float(a)) or math.isnan(float(b)):
            return False
        return round(float(a), 2) == round(float(b), 2)
    if isinstance(a, str) and isinstance(b, str):
        return unicodedata.normalize("NFC", a.strip()) == unicodedata.normalize("NFC", b.strip())
    return a == b


def _validate_prediction_schema(ans_type: str, ans_val) -> tuple[bool, object, str]:
    clean_type = str(ans_type).strip().lower()
    if clean_type not in VALID_ANSWER_TYPES:
        return False, None, f"invalid_type:{clean_type}"
    if clean_type in (AnswerType.ABSTAIN.value, AnswerType.UNANSWERABLE.value):
        return True, None, ""
    probe = {
        "kind": "final",
        "type": clean_type,
        "answer": ans_val,
        "evidence": "normalized_final",
    }
    try:
        _, validated = validate_protocol_payload(probe)
        return True, validated.get("answer"), ""
    except Exception as exc:
        return False, None, f"schema_error:{exc}"


def _looks_like_wrapped_payload(ans_type: str, ans_val) -> bool:
    """Model đôi khi nhét dict/JSON vào answer kiểu string; đó là đáp án sai format, không dùng làm kết quả đã xác minh."""
    if str(ans_type).strip().lower() != "string" or not isinstance(ans_val, str):
        return False
    t = ans_val.strip()
    return t[:1] in ("{", "[") and t[-1:] in ("}", "]")


def _digits_only(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _rescue_consistent_with_prose(raw_text: str, rescue_pred: dict) -> bool:
    """Final text không parse được: chỉ cứu kết quả run_python(final) cho unanswerable, date, string khi văn bản không mâu thuẫn.
    number/percent/list/table/boolean không cứu ở đây (đã có _extract_verified_scalar_from_prose, cố ý chặt)."""
    if not rescue_pred:
        return False
    r_type = str(rescue_pred.get("type", "")).strip().lower()
    r_ans = rescue_pred.get("answer")
    if r_type == AnswerType.UNANSWERABLE.value:
        return True
    if r_ans is None:
        return False
    cleaned = _strip_step_limit_header(raw_text)
    if not cleaned or len(cleaned) > 800 or _ABSTAIN_CUE_RE.search(cleaned):
        return False
    if r_type == "date" and isinstance(r_ans, str):
        found = []
        for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})/(\d{1,2})/(\d{4})\b", cleaned):
            if m.group(1):
                found.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
            else:
                found.append(f"{int(m.group(6)):04d}-{int(m.group(5)):02d}-{int(m.group(4)):02d}")
        return bool(found) and all(x == r_ans for x in found)
    if r_type == "string" and isinstance(r_ans, str):
        norm = lambda x: unicodedata.normalize("NFC", x).strip().casefold()
        if norm(r_ans) not in norm(cleaned):
            return False
        return all(norm(b) == norm(r_ans) for b in re.findall(r"\*\*(.+?)\*\*", cleaned))
    return False


def _coerce_month_string(typ: str, ans):
    """Model hay emit tháng dạng string "8/2025"; luật Mục 4: câu hỏi theo tháng là date "YYYY-MM"."""
    if typ == "string" and isinstance(ans, str):
        m = re.fullmatch(r"\s*(?:th[áa]ng\s*)?(\d{1,2})\s*[/-]\s*(\d{4})\s*", ans, flags=re.I)
        if m and 1 <= int(m[1]) <= 12:
            return "date", f"{m[2]}-{int(m[1]):02d}"
        m = re.fullmatch(r"\s*(\d{4})\s*[/-]\s*(\d{1,2})\s*", ans)   # đã đúng dạng YYYY-MM nhưng gắn type string
        if m and 1 <= int(m[2]) <= 12:
            return "date", f"{m[1]}-{int(m[2]):02d}"
    return typ, ans


def _extract_verified_tool_results_chronological(tool_calls: list) -> list[dict]:
    """Trả danh sách kết quả tính hợp lệ từ aggregate và run_python(final) đúng theo thứ tự thực thi."""
    verified = []
    for idx, tc in enumerate(tool_calls):
        if tc.get("status") != "completed":
            continue
        payload = tc.get("full_result")
        if payload is None:
            raw_out = tc.get("output")
            if isinstance(raw_out, str) and raw_out.strip():
                try:
                    payload = json.loads(raw_out)
                except json.JSONDecodeError:
                    payload = None
        if not isinstance(payload, dict) or payload.get("error"):
            continue
        if tc.get("tool") == "aggregate" and payload.get("type") and "answer" in payload:
            verified.append({
                "index": idx,
                "messageID": tc.get("messageID"),
                "source": "tool:aggregate",
                "type": str(payload["type"]).strip().lower(),
                "answer": payload["answer"],
            })
        elif tc.get("tool") == "run_python" and payload.get("success") is True:
            po = payload.get("parsed_output")
            if isinstance(po, dict) and po.get("kind") == "final" and po.get("type"):
                try:
                    _, v_po = validate_protocol_payload(dict(po))
                    if _looks_like_wrapped_payload(v_po["type"], v_po.get("answer")):
                        # final sai format là dấu hiệu đáp án mới nhất không đáng tin: không lùi về final cũ của câu khác nghĩa
                        verified.clear()
                        continue
                    verified.append({
                        "index": idx,
                        "messageID": tc.get("messageID"),
                        "source": "tool:run_python",
                        "type": _coerce_month_string(str(v_po["type"]).strip().lower(), v_po.get("answer"))[0],
                        "answer": _coerce_month_string(str(v_po["type"]).strip().lower(), v_po.get("answer"))[1],
                    })
                except Exception:
                    pass
    return verified


def normalize_final_answer(question_id: str, raw_final_text: str, tool_calls: list) -> dict:
    """Chuẩn hóa final answer đúng Mục 4, xử lý xung đột kiểu giữa các tool theo thứ tự phép tính cuối."""
    verified_results = _extract_verified_tool_results_chronological(tool_calls)
    has_valid_tool_final = bool(verified_results)

    rescue_pred = None
    if verified_results:
        last_verified = verified_results[-1]
        rescue_pred = SubmissionItem(id=question_id, type=last_verified["type"], answer=last_verified["answer"]).to_dict()

    stripped = (raw_final_text or "").strip()
    non_think = _strip_thinking_blocks(stripped)
    if not stripped or not non_think:
        if verified_results and last_verified["source"] == "tool:run_python":
            return {
                "prediction": rescue_pred,
                "type_source": "tool:run_python",
                "abstain_reason": None,
                "tool_succeeded_but_final_empty": True,
                "tool_rescue_prediction": rescue_pred,
            }
        return {
            "prediction": SubmissionItem.abstain(question_id, reason="empty_final").to_dict(),
            "type_source": "abstain",
            "abstain_reason": "empty_final",
            "tool_succeeded_but_final_empty": has_valid_tool_final,
            "tool_rescue_prediction": rescue_pred,
        }

    low_nt = non_think.lower()
    step_limit_banner = (
        low_nt.startswith("do not invoke any tools.")
        or "the maximum number of steps has been reached" in low_nt
        or "the maximum number of steps permitted" in low_nt
        or "đã đạt số bước cực đại" in low_nt
    )

    bare_val = None
    forced_bare_from_tool = False
    if step_limit_banner:
        if not verified_results:
            return {
                "prediction": SubmissionItem.abstain(question_id, reason="step_limit_reached").to_dict(),
                "type_source": "abstain",
                "abstain_reason": "step_limit_reached",
                "tool_succeeded_but_final_empty": False,
                "tool_rescue_prediction": rescue_pred,
            }
        ok_scalar, scalar_val = _extract_verified_scalar_from_prose(stripped, verified_results, max_len=4000)
        bare_val = scalar_val if ok_scalar else verified_results[-1]["answer"]
        forced_bare_from_tool = True

    if not forced_bare_from_tool:
        candidates = _try_parse_json_candidates(stripped)
        if not candidates:
            ok_scalar, scalar_val = _extract_verified_scalar_from_prose(stripped, verified_results)
            if ok_scalar:
                candidates = [scalar_val]
        if not candidates:
            if rescue_pred is not None and _rescue_consistent_with_prose(stripped, rescue_pred):
                return {
                    "prediction": rescue_pred,
                    "type_source": "tool:run_python",
                    "abstain_reason": None,
                    "tool_succeeded_but_final_empty": False,
                    "tool_rescue_prediction": rescue_pred,
                }
            return {
                "prediction": SubmissionItem.abstain(question_id, reason="unparseable_final").to_dict(),
                "type_source": "abstain",
                "abstain_reason": "unparseable_final",
                "tool_succeeded_but_final_empty": False,
                "tool_rescue_prediction": rescue_pred,
            }

        for cand in candidates:
            if isinstance(cand, dict) and "type" in cand and cand["type"] is not None:
                ok, norm_ans, err = _validate_prediction_schema(cand["type"], cand.get("answer"))
                if ok:
                    pred = SubmissionItem(id=question_id, type=str(cand["type"]).strip().lower(), answer=norm_ans).to_dict()
                    return {
                        "prediction": pred,
                        "type_source": "model",
                        "abstain_reason": None,
                        "tool_succeeded_but_final_empty": False,
                        "tool_rescue_prediction": rescue_pred,
                    }
                return {
                    "prediction": SubmissionItem.abstain(question_id, reason=err).to_dict(),
                    "type_source": "abstain",
                    "abstain_reason": err,
                    "tool_succeeded_but_final_empty": False,
                    "tool_rescue_prediction": rescue_pred,
                }

        for cand in candidates:
            if isinstance(cand, dict) and "answer" in cand:
                bare_val = cand["answer"]
                break
            if isinstance(cand, dict) and "columns" in cand and "rows" in cand:
                bare_val = cand
                break
            if not isinstance(cand, dict):
                bare_val = cand
                break

    matching = [r for r in verified_results if _values_match(bare_val, r["answer"])]
    if not matching:
        return {
            "prediction": SubmissionItem.abstain(question_id, reason="ambiguous_type_without_matching_tool").to_dict(),
            "type_source": "abstain",
            "abstain_reason": "ambiguous_type_without_matching_tool",
            "tool_succeeded_but_final_empty": False,
            "tool_rescue_prediction": rescue_pred,
        }

    matched_types = {r["type"] for r in matching}
    chosen = matching[-1]
    if len(matched_types) > 1:
        # Nếu nhiều tool trả cùng giá trị nhưng khác kiểu, chỉ nhận kiểu của phép tính cuối thực sự
        is_overall_last = chosen["index"] == verified_results[-1]["index"]
        same_turn_conflict = (
            chosen["messageID"] is not None
            and any(r["type"] != chosen["type"] and r["messageID"] == chosen["messageID"] for r in matching)
        )
        if not is_overall_last or same_turn_conflict:
            return {
                "prediction": SubmissionItem.abstain(question_id, reason="conflicting_tool_types").to_dict(),
                "type_source": "abstain",
                "abstain_reason": "conflicting_tool_types",
                "tool_succeeded_but_final_empty": False,
                "tool_rescue_prediction": rescue_pred,
            }

    ok, norm_ans, err = _validate_prediction_schema(chosen["type"], bare_val)
    if ok:
        pred = SubmissionItem(id=question_id, type=chosen["type"], answer=norm_ans).to_dict()
        return {
            "prediction": pred,
            "type_source": chosen["source"],
            "abstain_reason": None,
            "tool_succeeded_but_final_empty": False,
            "tool_rescue_prediction": rescue_pred,
        }
    return {
        "prediction": SubmissionItem.abstain(question_id, reason=err or "ambiguous_type_without_matching_tool").to_dict(),
        "type_source": "abstain",
        "abstain_reason": err or "ambiguous_type_without_matching_tool",
        "tool_succeeded_but_final_empty": False,
        "tool_rescue_prediction": rescue_pred,
    }


_CATALOG_CACHE: dict = {}
_CATALOG_LOCK = threading.Lock()


def build_data_catalog(shop_root: Path, env: dict, cache_key: str, max_chars: int = 4500) -> str:
    """Quét cấu trúc file của shop bằng chính tool inspect_table (không dùng model) và gom thành mục lục ngắn.
    Chỉ mô tả file/sheet/cột; không chứa quy tắc nghiệp vụ. Lỗi ở bất kỳ bước nào thì bỏ qua phần đó."""
    with _CATALOG_LOCK:
        if cache_key in _CATALOG_CACHE:
            return _CATALOG_CACHE[cache_key]
    lines, other = [], []
    files = sorted(p for p in shop_root.iterdir() if p.is_file() and p.name.lower() != "readme.md")
    for p in files:
        if p.suffix.lower() not in {".csv", ".xlsx", ".xls"} or len(lines) >= 12:
            other.append(p.name)
            continue
        try:
            proc = subprocess.run(
                [sys.executable, str(OPENCODE_RUNTIME_DIR / "bridge.py"), "inspect_table", json.dumps({"file": p.name, "column": None}, ensure_ascii=False)],
                env=env, capture_output=True, text=True, timeout=45, check=True,
            )
            info = json.loads(proc.stdout.strip())
        except Exception:
            other.append(p.name)
            continue
        previews = info.get("sheets_preview")
        if isinstance(previews, dict) and previews:
            groups: dict = {}
            for sname, sp in previews.items():
                sp = sp or {}
                cols = [str(c) for c in (sp.get("columns") or [])]
                hdr = sp.get("header_row_index")
                rows = [r for r in (sp.get("first_rows") or []) if isinstance(r, list)]
                if rows:
                    # header đoán của bridge có thể rơi vào khối tiêu đề sổ: lấy dòng đầu tiên có nhiều ô chữ nhất trong các dòng đầu
                    cnt = [len([c for c in r if str(c).strip()]) for r in rows]
                    k = cnt.index(max(cnt))
                    cols, hdr = [str(c) for c in rows[k] if str(c).strip()], (hdr if k == hdr else None)
                cols = list(dict.fromkeys(cols))[:24]
                groups.setdefault((hdr, tuple(cols)), []).append(sname)
            for (hdr, cols), names in groups.items():
                shown = ", ".join(f'"{n}"' for n in names[:4]) + (f" (+{len(names) - 4} sheet cùng cột)" if len(names) > 4 else "")
                lines.append(f"- {p.name} | sheet {shown}" + (f" | dòng tiêu đề {hdr + 1}" if isinstance(hdr, int) else "") + (f" | cột (đoán từ vài dòng đầu): {', '.join(cols)}" if cols else ""))
        else:
            cols = [str(c) for c in (info.get("columns") or [])][:30]
            lines.append(f"- {p.name} | cột (đoán từ vài dòng đầu): {', '.join(cols)}" if cols else f"- {p.name}")
    if other:
        lines.append("- file khác (xem bằng inspect_table / run_python): " + ", ".join(other[:15]) + (f" (+{len(other) - 15})" if len(other) > 15 else ""))
    text = ""
    if lines:
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars].rsplit("\n", 1)[0] + "\n- ... (còn nữa, dùng inspect_table để xem đầy đủ)"
        text = ("## Mục lục dữ liệu của shop (tự động quét cấu trúc; chỉ để định hướng, KHÔNG phải quy tắc tính; "
                "quy tắc và cách ghi dữ liệu vẫn lấy từ rulebook và README)\n" + text)
    with _CATALOG_LOCK:
        _CATALOG_CACHE[cache_key] = text
    return text


def run_single_question(
    question_item: QuestionItem,
    split_dir: Path,
    run_out_dir: Path,
    tool_mode: str,
    temperature: float,
    ollama_tag: str,
    ollama_port: int = 11434,
    worker_id: int = 0,
    per_question_timeout: float | None = None,
) -> dict:
    """Chạy 1 câu hỏi end-to-end qua OpenCode CLI + Ollama loopback và lưu trace đầy đủ."""
    t0 = time.time()
    per_q_timeout = float(per_question_timeout or PER_QUESTION_TIMEOUT_SEC)
    q_root_base = run_out_dir / "_shop_roots"
    shop_root = prepare_isolated_shop_root(question_item, split_dir, q_root_base)
    session_dir = setup_opencode_session_dir(run_out_dir / "_opencode_sessions" / f"{question_item.id}_w{worker_id}", tool_mode)
    work_dir = run_out_dir / "_python_workdir" / question_item.id
    work_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = run_out_dir / "_tool_sidecar" / f"{question_item.id}.jsonl"
    if sidecar_path.exists():
        sidecar_path.unlink()

    sys_instr_path = session_dir / "datamate_instructions.md"
    sys_instr_text = build_system_instructions(shop_root, tool_mode)
    sys_instr_path.write_text(sys_instr_text, encoding="utf-8")

    permissions = {"*": "deny", "read": "allow", "inspect_table": "allow", "aggregate": "allow"}
    if tool_mode == "eval_agent":
        permissions["run_python"] = "allow"
        permissions["explore_data"] = "allow"
    if tool_mode == "auto_readme_schema":
        permissions.pop("read", None)
    if "read" in permissions:
        # opencode asks a separate external_directory permission for paths it treats as outside the project;
        # without this the catch-all "*": "deny" blocks reading the shop README.
        permissions["external_directory"] = {
            str(shop_root): "allow", f"{shop_root}/*": "allow", f"{shop_root}/**": "allow",
        }

    effective_max_steps = MAX_STEPS_EVAL_AGENT if tool_mode == "eval_agent" else MAX_STEPS
    effective_tool_max_bytes = TOOL_MAX_BYTES_EVAL_AGENT if tool_mode == "eval_agent" else TOOL_MAX_BYTES

    instructions_order = (
        [str(RULEBOOK_PATH), str(sys_instr_path)]
        if tool_mode == "eval_agent"
        else [str(sys_instr_path), str(RULEBOOK_PATH)]
    )

    opencode_config = {
        "enabled_providers": ["ollama-local"],
        "provider": {
            "ollama-local": {
                "name": "Local Ollama",
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": f"http://127.0.0.1:{ollama_port}/v1"},
                "models": {
                    ollama_tag: {
                        "name": BASE_MODEL_TAG,
                        "tool_call": True,
                        "limit": {"context": NUM_CTX, "output": MAX_OUTPUT_TOKENS},
                    }
                },
            }
        },
        "model": f"ollama-local/{ollama_tag}",
        "small_model": f"ollama-local/{ollama_tag}",
        "instructions": instructions_order,
        "autoupdate": False,
        "share": "disabled",
        "compaction": {"auto": False},
        "tool_output": {"max_bytes": effective_tool_max_bytes},
        "permission": permissions,
        "agent": {"build": {"temperature": temperature, "steps": effective_max_steps}},
    }

    user_prompt = build_user_prompt(question_item, shop_root, tool_mode)
    env = os.environ.copy()
    for _tok_key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_HUB_TOKEN"):
        env.pop(_tok_key, None)
    env.update({
        "HOME": str(session_dir),
        "OPENCODE_CONFIG_DIR": str(session_dir),
        "OPENCODE_CONFIG_CONTENT": json.dumps(opencode_config, ensure_ascii=False),
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "DATAMATE_PYTHON_BIN": sys.executable,
        "DATAMATE_BRIDGE_PATH": str(OPENCODE_RUNTIME_DIR / "bridge.py"),
        "DATAMATE_SRC_ROOT": str(STRUCTURED_SRC_ROOT),
        "DATAMATE_DATA_ROOT": str(shop_root),
        "DATAMATE_WORK_DIR": str(work_dir),
        "DATAMATE_AS_OF_DATE": question_item.as_of_date,
        "DATAMATE_RULEBOOK_PATH": str(RULEBOOK_PATH),
        "DATAMATE_CALENDAR_PATH": str(CALENDAR_PATH) if CALENDAR_PATH else "",
        "DATAMATE_TIMEOUT_SEC": str(RUN_PYTHON_TIMEOUT_SEC),
        "DATAMATE_TOOL_TIMEOUT_MS": str(OPENCODE_TOOL_TIMEOUT_MS),
        "DATAMATE_TOOL_TRACE_PATH": str(sidecar_path),
        "DATAMATE_AUTO_WRAP_STDOUT": "1",
    })

    if os.environ.get("DATAMATE_CATALOG", "1") != "0":
        try:
            _cat = build_data_catalog(shop_root, env, f"{question_item.business_id}")
            if _cat:
                sys_instr_text += "\n\n" + _cat
                sys_instr_path.write_text(sys_instr_text, encoding="utf-8")
        except Exception:
            pass   # mục lục chỉ là gợi ý: lỗi thì bỏ qua, không làm hỏng câu hỏi

    cmd = [OPENCODE_BIN, "--pure", "-m", f"ollama-local/{ollama_tag}", "run", "--format", "json"]

    def run_turn(args: list[str], turn_env: dict, timeout: float):
        try:
            proc = subprocess.run(
                cmd + args, cwd=str(shop_root), env=turn_env, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout,
            )
            return proc.stdout or "", proc.stderr or "", proc.returncode, False
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
            return stdout or "", stderr or f"Timeout after {timeout:.0f}s", -1, True

    def parse_turns(stdout: str):
        sidecar_traces = []
        if sidecar_path.is_file():
            for line in sidecar_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        sidecar_traces.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return parse_opencode_jsonl_events(stdout, sidecar_traces=sidecar_traces)

    stdout_text, stderr_text, exit_code, timed_out = run_turn([user_prompt], env, per_q_timeout)
    parsed = parse_turns(stdout_text)
    norm = normalize_final_answer(
        question_item.id, "" if timed_out else parsed["raw_final_text"], parsed["tool_calls"]
    )
    recovery_attempted = False
    time_left = per_q_timeout - (time.time() - t0)
    _ran_python = any(tc["tool"] == "run_python" and tc["status"] == "completed" for tc in parsed["tool_calls"])
    # Lượt cuối bị cắt khi chưa chốt (suy luận dài hết token, nội dung rỗng): cho chạy tiếp cùng phiên, buộc ra bước tool kế tiếp
    _truncated = norm["abstain_reason"] == "empty_final" and not _ran_python and os.environ.get("DATAMATE_TRUNC_RECOVERY", "1") != "0"
    if (
        tool_mode == "eval_agent" and exit_code == 0 and parsed["session_id"] and time_left > 0
        and norm["abstain_reason"] and norm["tool_rescue_prediction"] is None
        and (_ran_python or _truncated)
    ):
        recovery_attempted = True
        if _ran_python:
            opencode_config["permission"] = {"*": "deny", "run_python": "allow"}
            opencode_config["agent"]["build"]["steps"] = 3
        else:
            opencode_config["permission"] = {**permissions, "*": "deny"}
            opencode_config["agent"]["build"]["steps"] = 8
        retry_env = {**env, "OPENCODE_CONFIG_CONTENT": json.dumps(opencode_config, ensure_ascii=False)}
        retry_prompt = (
            "Lượt trước bị cắt vì suy luận quá dài khi chưa có kết quả. KHÔNG suy luận dài thêm (tối đa vài câu mỗi lượt): "
            "chưa đủ dữ kiện thì gọi ngay một tool để lấy dữ kiện, đủ rồi thì gọi run_python tính và emit_final. "
            "Câu hỏi và rulebook vẫn như ban đầu; chỉ chốt khi dữ kiện đủ."
        ) if _truncated else (
            "Chốt câu hỏi ban đầu trong phiên này. Dựa vào file, sheet, cột và điều kiện đã xác minh, "
            "gọi ngay run_python để đọc dữ liệu gốc và tính đúng giá trị cần trả. "
            "Các helper emit_obs, emit_final, load_clean_df, explore_data, parse_vn_number, resolve_date đã có sẵn trong globals (KHÔNG import). Sau khi emit_final thành công, xuất câu trả lời cuối cùng chứa đáp án. "
            "Dòng cuối dùng emit_final(answer, type=..., evidence=...) với biến answer vừa tính. "
            "Giữ mọi xử lý trong bộ nhớ. Chỉ chốt khi có dữ kiện đủ để tính."
        )
        retry_stdout, retry_stderr, exit_code, timed_out = run_turn(
            ["--session", parsed["session_id"], retry_prompt], retry_env, min(time_left, 120 if _ran_python else 240)
        )
        parsed = parse_turns(stdout_text + "\n" + retry_stdout)
        stderr_text = "\n".join(s for s in (stderr_text, retry_stderr) if s)
        recovered = normalize_final_answer(question_item.id, "", parsed["tool_calls"])
        if recovered["type_source"] == "tool:run_python":
            recovered["tool_succeeded_but_final_empty"] = not _strip_thinking_blocks(parsed["raw_final_text"])
            norm = recovered

    if timed_out and norm["type_source"] != "tool:run_python":
        norm["abstain_reason"] = "question_timeout"
        norm["tool_succeeded_but_final_empty"] = False
    elapsed = round(time.time() - t0, 3)

    return {
        "id": question_item.id,
        "business_id": question_item.business_id,
        "as_of_date": question_item.as_of_date,
        "tool_mode": tool_mode,
        "temperature": temperature,
        "worker_id": worker_id,
        "ollama_port": ollama_port,
        "user_prompt": user_prompt,
        "system_instructions": sys_instr_text,
        "rulebook_path": str(RULEBOOK_PATH),
        "rulebook_sha256": RULEBOOK_SHA256,
        "shop_root": str(shop_root),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "finalization_retry_attempted": recovery_attempted,
        "elapsed_sec": elapsed,
        "finish_reason": parsed["finish_reason"],
        "final_message_id": parsed["final_message_id"],
        "tokens": parsed["token_summary"],
        "tool_calls": parsed["tool_calls"],
        "api_errors": parsed["api_errors"],
        "jsonl_parse_errors": parsed["jsonl_parse_errors"],
        "raw_final_text": parsed["raw_final_text"],
        "reasoning_texts": parsed.get("reasoning_texts", []),
        "text_messages": parsed.get("text_messages", []),
        "prediction": norm["prediction"],
        "type_source": norm["type_source"],
        "abstain_reason": norm["abstain_reason"],
        "tool_succeeded_but_final_empty": norm["tool_succeeded_but_final_empty"],
        "tool_rescue_prediction": norm["tool_rescue_prediction"],
        "stderr": stderr_text[-2000:] if stderr_text else "",
    }
