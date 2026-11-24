"""Compare LangChain and OpenCode on the same questions and local model.

Install requirements-langchain-pilot.txt alongside submission/requirements.txt.
Example:
    python scripts/evaluate_langchain_pilot.py --split data/train --qid QID --backend both
Run inference in an isolated environment with the split mounted read-only and without gold.
Score from outside that environment:
    python scripts/evaluate_langchain_pilot.py --score-run RESULT_DIR --gold REF.jsonl
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Literal


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "submission" / "runtime"


def jsonl(path):
    with path.open(encoding="utf-8-sig") as source:
        return [json.loads(line) for line in source if line.strip()]


def score_run(root, gold):
    from src.eval.scorer import evaluate_predictions, score_single_answer

    qids = json.loads((root / "manifest.json").read_text(encoding="utf-8"))["question_ids"]
    refs_by_id = {item["id"]: item for item in jsonl(gold)}
    if missing := set(qids) - refs_by_id.keys():
        raise ValueError(f"Gold missing selected IDs: {sorted(missing)}")
    refs = [refs_by_id[qid] for qid in qids]
    report = {}
    for backend in ("opencode", "langchain"):
        out = root / backend
        if not (out / "predictions.jsonl").is_file():
            continue
        preds = {item["id"]: item for item in jsonl(out / "predictions.jsonl")}
        if set(preds) != set(qids):
            raise ValueError(f"Incomplete predictions for {backend}.")
        traces = [json.loads((out / "traces" / f"{qid}.json").read_text(encoding="utf-8")) for qid in qids]
        report[backend] = {
            **asdict(evaluate_predictions(preds.values(), refs)),
            "elapsed_sec": round(sum(t["elapsed_sec"] for t in traces), 3),
            "tool_calls": sum(len(t["tool_calls"]) for t in traces),
            "tool_errors": sum(
                call.get("status") == "error"
                or (isinstance(call.get("full_result"), dict)
                    and (bool(call["full_result"].get("error")) or call["full_result"].get("success") is False))
                for t in traces for call in t["tool_calls"]
            ),
            "verdicts": {ref["id"]: score_single_answer(preds[ref["id"]], ref)[0] for ref in refs},
        }
    if not report:
        raise ValueError("No predictions to score.")
    (root / "scores.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def run_langchain(question, split, output, model_name, port, timeout):
    import httpx
    from langchain.agents import create_agent
    from langchain.agents.middleware import ModelCallLimitMiddleware, wrap_model_call
    from langchain.agents.structured_output import ToolStrategy
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI
    from langsmith import tracing_context
    from pydantic import BaseModel

    import agent_runner as baseline

    class SubmitAnswer(BaseModel):
        """Submit the type and value returned by the last successful calculation."""

        type: Literal["number", "percent", "string", "boolean", "date", "list", "table", "unanswerable", "abstain"]
        answer: Any

    started = time.monotonic()
    shop = baseline.prepare_isolated_shop_root(question, split, output / "_shop_roots")
    work = output / "_python_workdir" / question.id
    work.mkdir(parents=True)
    rulebook = split / "rulebook.md"
    calendar = split / "calendar.csv"
    env = {
        **{k: v for k, v in os.environ.items() if k not in ("HF_TOKEN", "HF_HUB_TOKEN", "HUGGING_FACE_HUB_TOKEN")},
        "DATAMATE_DATA_ROOT": str(shop),
        "DATAMATE_SRC_ROOT": str(RUNTIME),
        "DATAMATE_WORK_DIR": str(work),
        "DATAMATE_AS_OF_DATE": question.as_of_date,
        "DATAMATE_RULEBOOK_PATH": str(rulebook),
        "DATAMATE_CALENDAR_PATH": str(calendar) if calendar.is_file() else "",
        "DATAMATE_AUTO_WRAP_STDOUT": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    calls = []
    responses = []

    def remaining():
        return timeout - (time.monotonic() - started)

    def record(name, args, payload):
        calls.append({"tool": name, "status": "completed", "input": args, "full_result": payload})
        return payload

    def bridge(action, **args):
        left = remaining()
        if left <= 0:
            raise TimeoutError("Question time budget exceeded")
        tool_env = {**env, "DATAMATE_TIMEOUT_SEC": str(max(1, int(min(left, baseline.RUN_PYTHON_TIMEOUT_SEC))))}
        try:
            proc = subprocess.run(
                [sys.executable, str(RUNTIME / "bridge.py"), action, json.dumps(args, ensure_ascii=False)],
                env=tool_env, cwd=work, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=left, check=False,
            )
            payload = json.loads(proc.stdout)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            payload = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        return record(action, args, payload)

    @tool
    def read(filePath: str) -> Any:
        """Read the shop README in full. Pass its path from the system instructions."""
        readme = next((file for file in shop.iterdir() if file.name.lower() == "readme.md"), None)
        if readme is None or Path(filePath).name.lower() != "readme.md":
            return record("read", {"filePath": filePath}, {"error": "The shop README is unavailable."})
        return record("read", {"filePath": filePath}, readme.read_text(encoding="utf-8-sig"))

    @tool
    def inspect_table(file: str | None = None, column: str | None = None) -> dict:
        """List shop files, inspect a file's sheets and columns, or inspect a named column."""
        return bridge("inspect_table", file=file, column=column)

    @tool
    def explore_data(file: str, date: str | None = None, sheet: str | None = None,
                     column: str | None = None, keyword: str | None = None) -> dict:
        """Preview a shop table or the rows in a date window. Relative dates use as_of_date."""
        return bridge("explore_data", file=file, date=date, sheet=sheet, column=column, keyword=keyword)

    @tool
    def aggregate(file: str, operation: Literal["count_distinct"], date_column: str,
                  date_expression: str, as_of_date: str, column: str, status_column: str,
                  exclude_values: list[str]) -> dict:
        """Count distinct values in a CSV for a date window and status exclusions."""
        return bridge("aggregate", file=file, operation=operation, date_column=date_column,
                      date_expression=date_expression, as_of_date=as_of_date, column=column,
                      status_column=status_column, exclude_values=exclude_values)

    @tool
    def run_python(code: str) -> dict:
        """Compute from shop files with the existing Python helpers and emit_obs or emit_final."""
        return bridge("run_python", code=code)

    def set_request_timeout(request):
        if remaining() <= 0:
            raise TimeoutError("Question time budget exceeded")
        request.extensions["timeout"] = httpx.Timeout(remaining()).as_dict()

    @wrap_model_call
    def trace_model(request, handler):
        response = handler(request)
        responses.extend(msg.model_dump() for msg in response.result)
        return response

    instructions = baseline.build_system_instructions(shop, "eval_agent")
    instructions = instructions.replace(
        'BẮT BUỘC phải xuất đáp án cuối cùng trong câu trả lời (trả đúng giá trị JSON của `answer` ví dụ `42`, bỏ giải thích).',
        'Gọi SubmitAnswer với đúng type và answer từ kết quả tool.',
    )
    if os.environ.get("DATAMATE_CATALOG", "1") != "0":
        catalog = baseline.build_data_catalog(shop, env, question.business_id)
        if catalog:
            instructions += "\n\n" + catalog
    system = rulebook.read_text(encoding="utf-8-sig") + "\n\n" + instructions
    prompt = baseline.build_user_prompt(question, shop, "eval_agent")
    answer, error = None, None
    if remaining() > 0:
        with httpx.Client(trust_env=False, event_hooks={"request": [set_request_timeout]}) as http_client, tracing_context(enabled=False):
            model = ChatOpenAI(
                model=model_name, base_url=f"http://127.0.0.1:{port}/v1", api_key="local-ollama",
                temperature=0, seed=baseline.SEED, max_tokens=baseline.MAX_OUTPUT_TOKENS,
                max_retries=0, use_responses_api=False, timeout=remaining(), http_client=http_client,
            )
            agent = create_agent(
                model=model, system_prompt=system, tools=[read, inspect_table, explore_data, aggregate, run_python],
                response_format=ToolStrategy(SubmitAnswer),
                middleware=[
                    ModelCallLimitMiddleware(run_limit=baseline.MAX_STEPS_EVAL_AGENT, exit_behavior="end"),
                    trace_model,
                ],
            )
            try:
                state = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
                answer = state.get("structured_response")
            except Exception as exc:
                error = f"{type(exc).__name__}: {str(exc)[:800]}"
    else:
        error = "Question time budget exceeded during setup"

    verified = baseline._extract_verified_tool_results_chronological(calls)
    prediction = baseline.SubmissionItem.abstain(question.id).to_dict()
    reason = "missing_structured_final"
    if answer is not None:
        if answer.type == "abstain":
            reason = "model_abstain"
        else:
            kind, value = baseline._coerce_month_string(answer.type, answer.answer)
            ok, value, schema_error = baseline._validate_prediction_schema(kind, value)
            if not ok:
                reason = schema_error
            elif verified and verified[-1]["type"] == kind and baseline._values_match(verified[-1]["answer"], value):
                prediction = baseline.SubmissionItem(question.id, kind, value).to_dict()
                reason = None
            else:
                reason = "unverified_or_conflicting_final"
    if error:
        reason = "execution_error"
    return {
        "id": question.id, "prediction": prediction, "abstain_reason": reason,
        "elapsed_sec": round(time.monotonic() - started, 3), "error": error,
        "timed_out": remaining() <= 0,
        "system_instructions": system, "user_prompt": prompt,
        "tool_calls": calls, "model_responses": responses,
        "structured_response": answer.model_dump() if answer else None,
        "finish_reason": responses[-1]["response_metadata"].get("finish_reason") if responses else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    stage = parser.add_mutually_exclusive_group(required=True)
    stage.add_argument("--split", type=Path)
    stage.add_argument("--score-run", type=Path)
    parser.add_argument("--qid", action="append", help="Repeat to compare more questions.")
    parser.add_argument("--backend", choices=["langchain", "opencode", "both"], default="both")
    parser.add_argument("--model", default="ornith15-datamate-pilot-8k:latest")
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--gold", type=Path, help="Dev references for --score-run.")
    args = parser.parse_args()
    if args.score_run:
        if not args.gold or args.qid:
            parser.error("--score-run requires --gold and scores the IDs in the saved manifest.")
        sys.path.insert(0, str(ROOT))
        score_run(args.score_run, args.gold)
        return
    if args.gold or not args.qid:
        parser.error("Inference requires --qid. Use --score-run to score separately.")
    split = args.split.resolve()
    if args.timeout <= 0 or not (split / "rulebook.md").is_file():
        parser.error("Specify a positive timeout and a split containing rulebook.md.")
    os.environ.update(DATAMATE_SPLIT_DIR=str(split), DATAMATE_RUNTIME_DIR=str(RUNTIME))
    sys.path[:0] = [str(RUNTIME), str(ROOT / "submission" / "inference"), str(ROOT)]
    import agent_runner as baseline

    items = {item["id"]: item for item in jsonl(split / "questions.jsonl")}
    if missing := set(args.qid) - items.keys():
        parser.error(f"Unknown question IDs: {sorted(missing)}")
    questions = [baseline.QuestionItem.from_dict(items[qid]) for qid in dict.fromkeys(args.qid)]
    backends = ("opencode", "langchain") if args.backend == "both" else (args.backend,)
    result_root = ROOT / "result"
    result_root.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="langchain_pilot_", dir=result_root))
    print(f"Output: {root}", flush=True)
    manifest = {
        "model": args.model, "port": args.port, "temperature": 0, "seed": baseline.SEED,
        "max_steps": baseline.MAX_STEPS_EVAL_AGENT, "max_output_tokens": baseline.MAX_OUTPUT_TOKENS,
        "per_question_timeout_sec": args.timeout, "split": str(split), "question_ids": [q.id for q in questions],
        "rulebook_sha256": baseline.RULEBOOK_SHA256,
        "bridge_sha256": hashlib.sha256((RUNTIME / "bridge.py").read_bytes()).hexdigest(),
        "sandbox_sha256": hashlib.sha256((RUNTIME / "src/agent/sandbox.py").read_bytes()).hexdigest(),
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for backend in backends:
        out = root / backend
        traces = out / "traces"
        traces.mkdir(parents=True)
        with (out / "predictions.jsonl").open("w", encoding="utf-8") as predictions:
            for question in questions:
                print(f"{backend:<9} {question.id} running", flush=True)
                if backend == "opencode":
                    trace = baseline.run_single_question(
                        question, split, out, "eval_agent", 0, args.model, args.port,
                        per_question_timeout=args.timeout,
                    )
                else:
                    trace = run_langchain(question, split, out, args.model, args.port, args.timeout)
                (traces / f"{question.id}.json").write_text(
                    json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8",
                )
                predictions.write(json.dumps(trace["prediction"], ensure_ascii=False) + "\n")
                predictions.flush()
                print(f"{backend:<9} {question.id} {trace['prediction']['type']} {trace['elapsed_sec']}s "
                      f"{trace.get('abstain_reason') or ''}", flush=True)

if __name__ == "__main__":
    main()
