#!/usr/bin/env python3
"""DataMate inference entry point (called by /code/predict.sh).

Reads  /data/{questions.jsonl,rulebook.md,calendar.csv,data/<business_id>/...}
Writes /result/submission.jsonl  (one line per answered question, flushed immediately)
       /result/logs/             (one record per question: id, answer, elapsed_ms, thinking, code, output)

Pipeline per question: OpenCode 1.19.5 agent -> local Ollama (Ornith 1.5 9B, Q4_K_M GGUF)
-> tools inspect_table / aggregate / run_python (bridge.py) -> validated answer.
Everything is offline: Ollama and OpenCode only talk to 127.0.0.1.
"""
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

T_START = time.time()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DATA_DIR = Path(os.environ.get("DATAMATE_SPLIT_DIR", "/data"))
RESULT_DIR = Path(os.environ.get("DATAMATE_RESULT_DIR", "/result"))
LOG_DIR = RESULT_DIR / "logs"
MODELS_DIR = Path(os.environ.get("DATAMATE_OLLAMA_MODELS", "/code/models/ollama"))
WORK_DIR = Path(os.environ.get("DATAMATE_RUN_WORK_DIR", "/tmp/datamate_run"))

TIME_BUDGET_SEC = float(os.environ.get("DATAMATE_TIME_BUDGET_SEC", str(5 * 3600 + 40 * 60)))  # 6h limit, keep 20 min margin
DAEMONS_PER_GPU = int(os.environ.get("DATAMATE_DAEMONS_PER_GPU", "2"))
BASE_PORT = int(os.environ.get("DATAMATE_BASE_PORT", "11434"))
LIMIT = int(os.environ.get("DATAMATE_LIMIT", "0"))  # local smoke tests only; the organizers run without it
RUN_TAG = "datamate-run:latest"
BASE_MODEL_TAG = "ornith15-datamate-pilot-8k:latest"
EXPECTED_TEMPLATE_SHA256 = "f55f52930aa8bf44ab5cb85f99370fcc3c56e9a85640b812086d5330bce5d86b"

_log_lock = threading.Lock()


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with _log_lock, (LOG_DIR / "run.log").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def http_json(url: str, payload: dict | None = None, timeout: float = 60.0) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


# ----------------------------------------------------------------------------- GPUs / Ollama
def detect_gpu_ids() -> list[str]:
    forced = os.environ.get("DATAMATE_GPU_IDS", "").strip()
    if forced:
        return [g.strip() for g in forced.split(",") if g.strip()]
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    except Exception:
        return []


class Daemon:
    def __init__(self, idx: int, port: int, gpu: str | None):
        self.idx, self.port, self.gpu = idx, port, gpu
        self.proc: subprocess.Popen | None = None

    def start(self) -> bool:
        env = os.environ.copy()
        env.update({
            "OLLAMA_HOST": f"127.0.0.1:{self.port}",
            "OLLAMA_MODELS": str(MODELS_DIR),
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_MAX_LOADED_MODELS": "1",
            "OLLAMA_FLASH_ATTENTION": "1",
            "OLLAMA_KEEP_ALIVE": "24h",
            "OLLAMA_NOPRUNE": "1",
            "HOME": str(WORK_DIR / f"ollama_home_{self.idx}"),
        })
        Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
        if self.gpu is not None:
            env["CUDA_VISIBLE_DEVICES"] = self.gpu
        log_fh = open(LOG_DIR / f"ollama_daemon_{self.idx}.log", "w", encoding="utf-8")
        self.proc = subprocess.Popen(["ollama", "serve"], env=env, stdout=log_fh, stderr=subprocess.STDOUT)
        deadline = time.time() + 300
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False
            try:
                http_json(f"http://127.0.0.1:{self.port}/api/tags", timeout=2)
                return True
            except Exception:
                time.sleep(0.5)
        return False

    def prepare(self, num_ctx: int) -> bool:
        """Create the run tag (num_ctx / temperature 0 / seed) and load the model onto the GPU."""
        base = f"http://127.0.0.1:{self.port}"
        params = {
            "num_ctx": num_ctx, "temperature": 0.0, "seed": 42,
            "num_batch": 128, "presence_penalty": 0,
        }
        if os.environ.get("DATAMATE_NUM_GPU_LAYERS"):  # local small-VRAM testing only; unset in the submission
            params["num_gpu"] = int(os.environ["DATAMATE_NUM_GPU_LAYERS"])
        try:
            res = http_json(f"{base}/api/create", {
                "model": RUN_TAG,
                "from": BASE_MODEL_TAG,
                "parameters": params,
                "stream": False,
            }, timeout=1800)
            if res.get("status") != "success":
                log(f"daemon {self.idx}: create tag failed: {res}")
                return False
            if self.idx == 0:
                info = http_json(f"{base}/api/show", {"model": BASE_MODEL_TAG}, timeout=30)
                import hashlib
                sha = hashlib.sha256(info.get("template", "").encode("utf-8")).hexdigest()
                log(f"chat template sha256 {'OK' if sha == EXPECTED_TEMPLATE_SHA256 else 'MISMATCH'} ({sha[:12]})")
            http_json(f"{base}/api/generate", {
                "model": RUN_TAG, "prompt": "OK", "stream": False,
                "keep_alive": "24h", "options": {"num_predict": 1},
            }, timeout=1800)
            return True
        except Exception as exc:
            log(f"daemon {self.idx} (port {self.port}, gpu {self.gpu}) prepare failed: {exc!r}")
            return False

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# ----------------------------------------------------------------------------- output
class Output:
    def __init__(self, qids: list[str]):
        self.lock = threading.Lock()
        self.done: set[str] = set()
        self.sub = open(RESULT_DIR / "submission.jsonl", "w", encoding="utf-8")
        self.qlog = open(LOG_DIR / "questions.jsonl", "w", encoding="utf-8")
        (LOG_DIR / "traces").mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _flush(fh) -> None:
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass

    def write(self, qid: str, prediction: dict, record: dict, trace: dict | None) -> None:
        with self.lock:
            if qid in self.done:
                return
            self.done.add(qid)
            self.sub.write(json.dumps(prediction, ensure_ascii=False) + "\n")
            self._flush(self.sub)
            self.qlog.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._flush(self.qlog)
        if trace is not None:
            try:
                (LOG_DIR / "traces" / f"{qid}.json").write_text(
                    json.dumps(trace, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            except OSError:
                pass

    def close(self) -> None:
        for fh in (self.sub, self.qlog):
            try:
                fh.close()
            except OSError:
                pass


def abstain_pred(qid: str) -> dict:
    return {"id": qid, "type": "abstain", "answer": None}


THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


def collect_thinking(result: dict):
    """Reasoning exactly as generated: reasoning events first, else <think> blocks from the text. None if absent."""
    items = [t for t in result.get("reasoning_texts", []) if t and t.strip()]
    if not items:
        for msg in result.get("text_messages", []):
            items.extend(m.strip() for m in THINK_RE.findall(msg or "") if m.strip())
    if not items:
        return None
    return items[0] if len(items) == 1 else items


def tool_output(tc: dict):
    """The computed value of a tool call: the final answer when there is one, else the raw tool output."""
    payload = tc.get("full_result")
    if payload is None and isinstance(tc.get("output"), str):
        try:
            payload = json.loads(tc["output"])
        except (json.JSONDecodeError, ValueError):
            return tc.get("output")
    if isinstance(payload, dict):
        po = payload.get("parsed_output")
        if isinstance(po, dict):
            return po.get("answer") if po.get("kind") == "final" else po.get("data")
        if "answer" in payload:
            return payload["answer"]
    return payload


def build_record(result: dict) -> dict:
    calls = result.get("tool_calls", []) or []
    codes, outputs, inputs = [], [], []
    for tc in calls:
        if tc.get("status") != "completed":
            continue
        if tc.get("tool") == "run_python" and isinstance(tc.get("input"), dict):
            codes.append(str(tc["input"].get("code", "")))
            outputs.append(tool_output(tc))
        elif tc.get("tool") == "aggregate":
            codes.append("runtime/bridge.py::count_distinct")
            inputs.append(tc.get("input"))
            outputs.append(tool_output(tc))
    code = None
    if codes:
        code = codes[-1] if len(codes) == 1 else "\n\n# ---- next execution ----\n".join(codes)
    pred = result["prediction"]
    return {
        "id": result["id"],
        "answer": {"type": pred.get("type"), "answer": pred.get("answer")},
        "elapsed_ms": max(0, int(round(float(result.get("elapsed_sec", 0.0)) * 1000))),
        "thinking": collect_thinking(result),
        "code": code,
        "inputs": inputs or None,
        "output": outputs[-1] if outputs else None,
        "abstain_reason": result.get("abstain_reason"),
        "type_source": result.get("type_source"),
        "tool_calls": len(calls),
        "max_step_input_tokens": (result.get("tokens") or {}).get("max_step_input"),
        "steps": (result.get("tokens") or {}).get("steps"),
        "worker_id": result.get("worker_id"),
    }


# ----------------------------------------------------------------------------- main
def load_questions() -> list:
    from agent_runner import QuestionItem
    items = []
    with (DATA_DIR / "questions.jsonl").open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if not line.strip():
                continue
            raw = json.loads(line)
            try:
                items.append(QuestionItem.from_dict(raw))
            except Exception as exc:  # malformed question -> still answer (abstain) by raw id
                log(f"invalid question {raw.get('id')}: {exc}")
                items.append(raw)
    return items


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    log(f"start; data={DATA_DIR} budget={TIME_BUDGET_SEC:.0f}s daemons/gpu={DAEMONS_PER_GPU}")

    questions = load_questions()
    if LIMIT:
        questions = questions[:LIMIT]
    qids = [q.id if hasattr(q, "id") else str(q.get("id")) for q in questions]
    out = Output(qids)
    daemons: list[Daemon] = []

    def finalize() -> None:
        missing = [q for q in qids if q not in out.done]
        for qid in missing:
            out.write(qid, abstain_pred(qid),
                      {"id": qid, "answer": {"type": "abstain", "answer": None}, "elapsed_ms": 0,
                       "thinking": None, "code": None, "output": None, "abstain_reason": "not_processed"}, None)
        for d in daemons:
            d.stop()
        out.close()
        summary = {"questions": len(qids), "abstained_unprocessed": len(missing),
                   "total_elapsed_sec": round(time.time() - T_START, 1)}
        (LOG_DIR / "run_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        log(f"done: {summary}")

    def on_term(signum, frame):  # organizers stop the container at the limit; answers are already on disk
        log(f"signal {signum}: finalizing")
        finalize()
        os._exit(0)

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    try:
        gpus = detect_gpu_ids()
        log(f"gpus: {gpus or 'none detected'}")
        if not gpus:
            log("no GPU -> every question abstains (nothing else is safe at this speed)")
            finalize()
            return 0
        idx = 0
        for g in gpus:
            for _ in range(DAEMONS_PER_GPU):
                daemons.append(Daemon(idx, BASE_PORT + idx, g))
                idx += 1

        import agent_runner as ar
        num_ctx = ar.NUM_CTX
        ok: list[Daemon] = []
        lock = threading.Lock()

        def boot(d: Daemon) -> None:
            if not d.start():
                d.stop()
                return
            for attempt in range(1, 4):  # cold model reads can be slow; never give up after one miss
                if d.prepare(num_ctx):
                    with lock:
                        ok.append(d)
                    return
                log(f"daemon {d.idx}: prepare attempt {attempt}/3 failed, retrying")
                time.sleep(5)
            d.stop()

        threads = [threading.Thread(target=boot, args=(d,)) for d in daemons]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        daemons[:] = ok or daemons
        log(f"model ready on {len(ok)}/{len(daemons)} daemons after {time.time() - T_START:.0f}s")
        if not ok:
            finalize()
            return 0

        deadline = T_START + TIME_BUDGET_SEC
        pending = list(questions)
        plock = threading.Lock()
        run_out_dir = WORK_DIR / "agent"
        run_out_dir.mkdir(parents=True, exist_ok=True)

        def worker(d: Daemon, wid: int) -> None:
            while True:
                with plock:
                    if not pending:
                        return
                    q = pending.pop(0)
                qid = q.id if hasattr(q, "id") else str(q.get("id"))
                left = deadline - time.time()
                if left < 60 or not hasattr(q, "id"):
                    out.write(qid, abstain_pred(qid),
                              {"id": qid, "answer": {"type": "abstain", "answer": None}, "elapsed_ms": 0,
                               "thinking": None, "code": None, "output": None,
                               "abstain_reason": "time_budget" if hasattr(q, "id") else "invalid_question"}, None)
                    continue
                t0 = time.time()
                try:
                    res = ar.run_single_question(
                        q, DATA_DIR, run_out_dir, "eval_agent", 0.0, RUN_TAG,
                        ollama_port=d.port, worker_id=wid,
                        per_question_timeout=min(ar.PER_QUESTION_TIMEOUT_SEC, max(45.0, left - 30)),
                    )
                    out.write(qid, res["prediction"], build_record(res), res)
                except Exception as exc:
                    log(f"{qid}: runner error {exc!r}")
                    out.write(qid, abstain_pred(qid),
                              {"id": qid, "answer": {"type": "abstain", "answer": None},
                               "elapsed_ms": int((time.time() - t0) * 1000), "thinking": None,
                               "code": None, "output": None, "abstain_reason": f"runner_error: {exc!r}"[:300]}, None)
                finally:
                    # free the per-question scratch copies (shop data + opencode session dir)
                    for sub in ("_shop_roots", "_opencode_sessions", "_python_workdir"):
                        for p in (run_out_dir / sub).glob(f"{qid}*"):
                            ar.shutil.rmtree(p, ignore_errors=True)
                n = len(out.done)
                if n % 10 == 0 or n == len(qids):
                    log(f"progress {n}/{len(qids)} elapsed={time.time() - T_START:.0f}s")

        workers = [threading.Thread(target=worker, args=(d, i)) for i, d in enumerate(ok)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
    except Exception as exc:
        log(f"fatal: {exc!r}")
    finally:
        finalize()
    return 0


if __name__ == "__main__":
    sys.exit(main())
