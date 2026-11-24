#!/usr/bin/env python3
"""Assemble the Docker build context in <repo>/submission/ (run once, before `docker build`).

* copies the agent runtime (bridge.py, run.js, tools/, src/) from tmp/opencode-structured -> submission/runtime
* copies ONLY the Ollama files of the tag `ornith15-datamate-pilot-8k` (manifest + referenced blobs) -> submission/models/ollama
  (hard links when possible, so no extra disk space)
* writes submission/training_code/data_manifest.json with SHA-256 checksums
* optionally copies pre-staged OpenCode node_modules (--node-modules)

Usage (Windows or Linux):  python scripts/prepare_submission.py [--ollama-models D:\\ollama\\model] [--node-modules DIR]
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

TAG_DIR = "ornith15-datamate-pilot-8k"
EXPECTED_MANIFEST_SHA256 = "57ad8bec8adf0a704a07a26adb2abf9edae310ba0fd3cef575d02dac1af69bb5"
EXPECTED_BLOBS = {
    "852922174ee4f76621df26105333f1dfe2171cdfb60ebe5a4b013836681a8a77",
    "2635637dd72b4d39a97331373a73366b69a0a6a14151b2a1da0a97b311e2461f",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


MANIFEST_DIRS = ("manifests", "manifests-v2")  # newer Ollama writes manifests-v2/ + metadata/


def find_manifests(root: Path) -> list[Path]:
    found = []
    for d in MANIFEST_DIRS:
        base = root / d
        if base.is_dir():
            found += [p for p in base.rglob("*") if p.is_file() and p.parent.name == TAG_DIR]
    return found


def find_models_root(hint: str | None) -> Path:
    """First model store that actually contains the manifest of TAG_DIR (a machine can have several stores)."""
    cands = [Path(hint)] if hint else []
    if os.environ.get("OLLAMA_MODELS"):
        cands.append(Path(os.environ["OLLAMA_MODELS"]))
    cands += [Path.home() / ".ollama" / "models", Path(r"D:\Ollama\model"), Path(r"D:\ollama\models")]
    seen = []
    for c in cands:
        for root in (c, c / "models"):
            if (root / "blobs").is_dir():
                seen.append(str(root))
                if find_manifests(root):
                    print(f"model store: {root}")
                    return root
    sys.exit(f"No Ollama model store contains the tag {TAG_DIR}. Searched: {seen or cands}. "
             "Pass --ollama-models <dir that contains manifests/ and blobs/>.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--ollama-models", default=None)
    ap.add_argument("--node-modules", default=None, help="optional pre-staged OpenCode node_modules")
    args = ap.parse_args()

    repo = Path(args.repo)
    sub = repo / "submission"
    rt_src = repo / "tmp" / "opencode-structured"
    for need in ("bridge.py", "run.js", "tools", "src"):
        if not (rt_src / need).exists():
            sys.exit(f"missing {rt_src / need}")

    # 1) runtime
    rt_dst = sub / "runtime"
    if rt_dst.exists():
        shutil.rmtree(rt_dst)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "coder_training")
    rt_dst.mkdir(parents=True)
    shutil.copy2(rt_src / "bridge.py", rt_dst / "bridge.py")
    shutil.copy2(rt_src / "run.js", rt_dst / "run.js")
    shutil.copytree(rt_src / "tools", rt_dst / "tools", ignore=ignore)
    shutil.copytree(rt_src / "src", rt_dst / "src", ignore=ignore)
    print(f"runtime -> {rt_dst}")

    # 2) Ollama model files
    root = find_models_root(args.ollama_models)
    manifests = find_manifests(root)
    if not manifests:
        sys.exit(f"manifest for {TAG_DIR} not found under {root}")
    manifest_path = manifests[0]
    manifest_sha = sha256_file(manifest_path)
    if manifest_sha != EXPECTED_MANIFEST_SHA256:
        print(f"WARNING: manifest sha256 {manifest_sha} != expected {EXPECTED_MANIFEST_SHA256}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digests = [manifest["config"]["digest"]] + [layer["digest"] for layer in manifest["layers"]]

    out_models = sub / "models" / "ollama"
    if out_models.exists():
        shutil.rmtree(out_models)
    files = []
    for mp in manifests:  # keep every manifest layout (manifests/ and manifests-v2/) exactly as Ollama wrote it
        top = next(d for d in MANIFEST_DIRS if (root / d) in mp.parents)
        link_or_copy(mp, out_models / top / mp.relative_to(root / top))
    for dg in digests:
        name = dg.replace(":", "-")
        src = root / "blobs" / name
        if not src.is_file():
            sys.exit(f"blob {name} not found in {root / 'blobs'}")
        link_or_copy(src, out_models / "blobs" / name)
        digest_hex = dg.split(":")[1]
        actual = sha256_file(src)
        if actual != digest_hex:
            sys.exit(f"blob {name} is corrupt (sha256 {actual})")
        files.append({"path": f"models/ollama/blobs/{name}", "bytes": src.stat().st_size, "sha256": actual})
        meta = root / "metadata" / f"{name}.json"
        if meta.is_file():
            link_or_copy(meta, out_models / "metadata" / meta.name)
        print(f"blob {name[:19]}... {src.stat().st_size / 1e9:.2f} GB ok")
    missing = EXPECTED_BLOBS - {f["sha256"] for f in files}
    if missing:
        print(f"WARNING: expected weight blobs not in manifest: {sorted(missing)}")
    files.append({"path": "models/ollama/" + manifest_path.relative_to(root).as_posix(),
                  "bytes": manifest_path.stat().st_size, "sha256": manifest_sha})

    # 3) optional node_modules
    if args.node_modules:
        dst = sub / "opencode_node_modules"
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(args.node_modules, dst)
        (dst / ".keep").touch()
        print(f"node_modules -> {dst}")

    # 4) data manifest (no training performed)
    manifest_out = {
        "training_performed": False,
        "base_model": {
            "name": "Ornith 1.5 9B", "source": "https://huggingface.co/ornith-ai/Ornith-1.5-9B",
            "ollama_tag": "ornith-1.5:9b (Q4_K_M)", "license": "MIT",
        },
        "files": files,
        "datasets": {"train_samples": 0, "validation_samples": 0, "synthetic_samples": 0},
    }
    (sub / "training_code").mkdir(parents=True, exist_ok=True)
    (sub / "training_code" / "data_manifest.json").write_text(json.dumps(manifest_out, indent=2), encoding="utf-8")

    readme = (sub / "README.md").read_text(encoding="utf-8")
    if "TODO_FILL" in readme:
        print("\nTODO: fill the TODO_FILL fields in submission/README.md (release date, HF revision) before building.")
    print("\nNext:\n  docker build --platform linux/amd64 -t zaic2026_datamate_<team_name>:final submission/")


if __name__ == "__main__":
    main()
