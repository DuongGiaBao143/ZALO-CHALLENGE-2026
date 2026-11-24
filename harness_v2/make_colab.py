"""Đóng gói để chạy harness_v2 trên Colab: tmp/harness_v2_code.zip + tmp/harness_v2_data.zip và notebooks/Harness_v2_Colab.ipynb.

Chạy: python -m harness_v2.make_colab [--code-only] [--upload REPO]
Gói zip có chứa đáp án (cần để chấm). Solver không đọc được: tool read chỉ mở README/rulebook, run_python bị giới hạn trong thư mục shop."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from harness_v2.evalsets import ROOT, load_jsonl, unseen_50

TEMPLATE = ROOT / ".claude" / "worktrees" / "pipeline-info-649698" / "pipelines" / "ornith_rft" / "ollama_template.jinja"


def _zip(out: Path, adders) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        def add(p: Path, arc: str | None = None):
            z.write(p, arc or p.relative_to(ROOT).as_posix())
        adders(add)
    print(f"{out} ({out.stat().st_size / 2**20:.1f} MB)")


def build_code_zip(out: Path) -> None:
    """Code (nhỏ, đổi thường xuyên): harness_v2, src, submission/runtime, template."""
    def adders(add):
        for base in (ROOT / "harness_v2", ROOT / "harness_v2" / "solvers"):
            for p in base.glob("*.py"):
                add(p)
        for base in (ROOT / "src", ROOT / "submission" / "runtime"):
            for p in base.rglob("*"):
                if p.is_file() and "__pycache__" not in p.parts and "node_modules" not in p.parts and p.suffix in {".py", ".json", ".md", ".csv"}:
                    add(p)
        if TEMPLATE.exists():
            add(TEMPLATE, "harness_v2/ollama_template.jinja")
    _zip(out, adders)


def build_data_zip(out: Path) -> None:
    """Dữ liệu + đáp án của hai bộ câu (lớn, hiếm đổi)."""
    def adders(add):
        add(ROOT / "eval_gold" / "unseen_gold_50.jsonl")
        for p in (ROOT / "data" / "private_test" / "private_test").rglob("*"):
            if p.is_file():
                add(p)
        train = ROOT / "data" / "train"
        for f in ("questions.jsonl", "rulebook.md", "calendar.csv"):
            add(train / f)
        for b in sorted({it["business_id"] for it in unseen_50().items}):
            for p in (train / "data" / b).rglob("*"):
                if p.is_file():
                    add(p)
    _zip(out, adders)


def upload(repo: str, files: list[Path]) -> None:
    """Đẩy lên dataset repo PRIVATE của chính bạn (tạo nếu chưa có). Chứa đáp án nên không bao giờ để public."""
    from huggingface_hub import HfApi
    api = HfApi()
    api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
    assert api.repo_info(repo, repo_type="dataset").private, "repo phải private"
    for f in files:
        api.upload_file(path_or_fileobj=str(f), path_in_repo=f.name, repo_id=repo, repo_type="dataset")
        print("đã đẩy", f.name, "->", repo)


CELLS = [
    ("md", "# harness_v2 (M1) trên Colab\n\nChạy agent tự viết trên `unseen_50` / `private_50`, in PA. Cần GPU (A100/G4). Cần Colab Secret `HF_TOKEN` đọc được dataset repo private `Crinkk/datamate-harness-v2` (đổi bằng env `HV2_REPO`)."),
    ("code", r'''
import os, subprocess, sys, zipfile
from pathlib import Path
def sh(cmd): print("$", cmd); subprocess.run(cmd, shell=True, check=True)
HV2_REPO = os.environ.get("HV2_REPO", "Crinkk/datamate-harness-v2")   # dataset repo private chứa code.zip + data.zip
try:
    from google.colab import userdata; os.environ["HF_TOKEN"] = userdata.get("HF_TOKEN") or os.environ.get("HF_TOKEN", "")
except Exception: pass
sh("pip install -q -U huggingface_hub")
from huggingface_hub import hf_hub_download
import shutil
PROJ = Path("/content/proj")
if os.environ.get("HV2_REFRESH_DATA", "0") == "1" or not (PROJ / "data").exists():   # data.zip lớn: chỉ tải lần đầu
    shutil.rmtree(PROJ, ignore_errors=True)
    zipfile.ZipFile(hf_hub_download(HV2_REPO, "harness_v2_data.zip", repo_type="dataset")).extractall(PROJ)
shutil.rmtree(PROJ / "harness_v2", ignore_errors=True)   # code.zip nhỏ: luôn lấy bản mới nhất
zipfile.ZipFile(hf_hub_download(HV2_REPO, "harness_v2_code.zip", repo_type="dataset", force_download=True)).extractall(PROJ)
sh("pip install -q pandas openpyxl rapidfuzz")
from importlib.metadata import version
try: _v = tuple(int(x) for x in version("vllm").split(".")[:3])
except Exception: _v = (0,)
if _v < (0, 19, 1): sh("pip install -q -U 'vllm>=0.19.1'")
import torch; assert torch.cuda.is_available(), "Cần GPU"
print("OK", PROJ)
'''),
    ("code", r'''
import os, subprocess, time, urllib.request
from pathlib import Path
MODEL_ID = os.environ.get("HV2_MODEL_ID", "ornith-ai/Ornith-1.5-9B")
PORT = 8000
try:
    from google.colab import userdata; os.environ["HF_TOKEN"] = userdata.get("HF_TOKEN") or os.environ.get("HF_TOKEN", "")
except Exception: pass
PARSER = os.environ.get("HV2_TOOL_PARSER", "qwen3_xml")           # parser gọi tool của vLLM; đổi theo họ model
REASONING = os.environ.get("HV2_REASONING_PARSER", "qwen3")        # "none" nếu model không có chế độ suy nghĩ
TEMPLATE = os.environ.get("HV2_CHAT_TEMPLATE", "/content/proj/harness_v2/ollama_template.jinja")   # "none" = dùng template có sẵn của model
cmd = ["vllm", "serve", MODEL_ID, "--served-model-name", "ornith", "--host", "127.0.0.1", "--port", str(PORT),
       "--max-model-len", os.environ.get("HV2_MAX_LEN", "65536"), "--gpu-memory-utilization", "0.90", "--max-num-seqs", "8", "--enable-prefix-caching",
       "--enable-auto-tool-choice", "--tool-call-parser", PARSER, "--trust-remote-code", "--seed", "0"]
if REASONING.lower() != "none": cmd += ["--reasoning-parser", REASONING]
if TEMPLATE.lower() != "none": cmd += ["--chat-template", TEMPLATE]
if os.environ.get("HV2_TEXT_ONLY", "1") == "1": cmd += ["--limit-mm-per-prompt", '{"image": 0, "video": 0}']   # model không có phần ảnh thì đặt 0
log = open("/content/vllm_server.log", "w")
SERVER = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
t0 = time.time()
while time.time() - t0 < 1800:
    if SERVER.poll() is not None: raise RuntimeError("vLLM thoát sớm:\n" + "".join(open("/content/vllm_server.log").readlines()[-40:]))
    try:
        if urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=2).status == 200: break
    except Exception: time.sleep(3)
else: raise RuntimeError("vLLM không lên sau 30 phút")
print("vLLM sẵn sàng sau", round(time.time() - t0), "s")
'''),
    ("code", r'''
# Cấu hình lần chạy (đổi rồi chạy lại cell này; mỗi RUN_TAG ghi vào thư mục riêng)
SET     = os.environ.get("HV2_SET", "private_50")      # unseen_50 | private_50
RUN_TAG = os.environ.get("HV2_TAG", "agent_v1")
WORKERS = int(os.environ.get("HV2_WORKERS", 4))
LIMIT   = int(os.environ.get("HV2_LIMIT", 0)) or None  # đặt 5 để chạy thử vài câu
os.environ.update({"HV2_BASE_URL": f"http://127.0.0.1:{PORT}/v1", "HV2_MODEL": "ornith",
                   "HV2_TRACE_DIR": f"/content/proj/runs/{RUN_TAG}_{SET}/traces"})
out = f"runs/{RUN_TAG}_{SET}/predictions.jsonl"
cmd = f"cd /content/proj && python -m harness_v2.run --set {SET} --solver harness_v2.solvers.agent_v1:solve --out {out} --workers {WORKERS}" + (f" --limit {LIMIT}" if LIMIT else "")
get_ipython().system(cmd)
'''),
    ("code", r'''
get_ipython().system(f"cd /content/proj && python -m harness_v2.score --set {SET} --preds {out}")
import shutil; shutil.make_archive(f"/content/{RUN_TAG}_{SET}", "zip", f"/content/proj/runs/{RUN_TAG}_{SET}")
print(f"Kết quả + trace: /content/{RUN_TAG}_{SET}.zip (tải về từ panel Files)")
'''),
]


def build_notebook(out: Path) -> None:
    cells = [{"cell_type": "markdown" if k == "md" else "code", "metadata": {}, "source": s.strip("\n").splitlines(True),
              **({} if k == "md" else {"outputs": [], "execution_count": None})} for k, s in CELLS]
    nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
          "accelerator": "GPU", "colab": {"gpuType": "A100"}}, "nbformat": 4, "nbformat_minor": 5}
    out.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-only", action="store_true", help="chỉ đóng gói code (nhanh), bỏ qua data.zip")
    ap.add_argument("--upload", metavar="REPO", help="đẩy lên dataset repo private, vd Crinkk/datamate-harness-v2")
    a = ap.parse_args()
    tmp = ROOT / "tmp"
    files = [tmp / "harness_v2_code.zip"]
    build_code_zip(files[0])
    if not a.code_only:
        files.append(tmp / "harness_v2_data.zip")
        build_data_zip(files[1])
    build_notebook(ROOT / "notebooks" / "Harness_v2_Colab.ipynb")
    if a.upload:
        upload(a.upload, files)
