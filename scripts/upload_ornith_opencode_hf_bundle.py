"""Package and upload clean Ornith + OpenCode Kaggle inputs to Hugging Face."""

from __future__ import annotations

import argparse
import hashlib
import os
import zipfile
from pathlib import Path

from huggingface_hub import HfApi

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OLLAMA_MODEL_ROOT = Path(r"D:\ollama\model")
DEFAULT_REPO_ID = "Crinkk/Zalo-challenge"
INFERENCE_BUNDLE_PATH_IN_REPO = "ornith_opencode_kaggle/ornith_opencode_inference_bundle_v3.zip"  # v1 and v2 files are kept as is for reproducing old runs

EXPECTED_SANDBOX_PREFIX = "dd948cb04cda"  # v3: explore_data date window recognises total rows with filled dates; v2 was 84678416dd8e, v1 7b8bb34772d8
EXPECTED_MANIFEST_SHA256 = "57ad8bec8adf0a704a07a26adb2abf9edae310ba0fd3cef575d02dac1af69bb5"
LARGE_BLOB_NAMES = [
    "sha256-2635637dd72b4d39a97331373a73366b69a0a6a14151b2a1da0a97b311e2461f",
    "sha256-852922174ee4f76621df26105333f1dfe2171cdfb60ebe5a4b013836681a8a77",
]
SMALL_OVERLAY_FILES = [
    (
        "manifests-v2/ollama.com/library/ornith15-datamate-pilot-8k/latest",
        "ollama_pilot_overlay/manifests-v2/ollama.com/library/ornith15-datamate-pilot-8k/latest",
    ),
    (
        "manifests-v2/ollama.com/library/ornith15-datamate-pilot-8k/latest",
        "ollama_pilot_overlay/manifests/registry.ollama.ai/library/ornith15-datamate-pilot-8k/latest",
    ),
    (
        "blobs/sha256-57ad8bec8adf0a704a07a26adb2abf9edae310ba0fd3cef575d02dac1af69bb5",
        "ollama_pilot_overlay/blobs/sha256-57ad8bec8adf0a704a07a26adb2abf9edae310ba0fd3cef575d02dac1af69bb5",
    ),
    (
        "blobs/sha256-055501390333b9dfb77db59953edd4c1d36413ffe9376cb209c0913ea19f3e87",
        "ollama_pilot_overlay/blobs/sha256-055501390333b9dfb77db59953edd4c1d36413ffe9376cb209c0913ea19f3e87",
    ),
    (
        "blobs/sha256-5b1ae7a9bd071e6f876a143822b865677caa747ac2cfa8e3b35ce84ee51bb520",
        "ollama_pilot_overlay/blobs/sha256-5b1ae7a9bd071e6f876a143822b865677caa747ac2cfa8e3b35ce84ee51bb520",
    ),
    (
        "metadata/sha256-852922174ee4f76621df26105333f1dfe2171cdfb60ebe5a4b013836681a8a77.json",
        "ollama_pilot_overlay/metadata/sha256-852922174ee4f76621df26105333f1dfe2171cdfb60ebe5a4b013836681a8a77.json",
    ),
    (
        "metadata/sha256-2635637dd72b4d39a97331373a73366b69a0a6a14151b2a1da0a97b311e2461f.json",
        "ollama_pilot_overlay/metadata/sha256-2635637dd72b4d39a97331373a73366b69a0a6a14151b2a1da0a97b311e2461f.json",
    ),
]


def _should_skip_tree_file(path: Path) -> bool:
    if "__pycache__" in path.parts:
        return True
    return path.suffix.lower() in {".pyc", ".pyo"}


def _is_forbidden_in_inference_zip(arcname: str) -> bool:
    low = arcname.lower()
    return "answers.jsonl" in low or "gold" in low


def build_inference_bundle(out_zip: Path, ollama_model_root: Path) -> Path:
    """Create strict inference-only zip (zero answers/gold files)."""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()

    train_root = REPO_ROOT / "data" / "train"
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for rel in ("questions.jsonl", "rulebook.md", "calendar.csv"):
            src = train_root / rel
            assert src.is_file(), f"Missing {src}"
            zf.write(src, f"data/train/{rel}")

        shops_dir = train_root / "data"
        for src in sorted(shops_dir.rglob("*")):
            if not src.is_file() or _should_skip_tree_file(src):
                continue
            arc = f"data/train/data/{src.relative_to(shops_dir).as_posix()}"
            if _is_forbidden_in_inference_zip(arc):
                raise RuntimeError(f"Refusing to include reference-like file in inference bundle: {arc}")
            zf.write(src, arc)

        for folder, prefix in [
            (REPO_ROOT / "src", "src"),
            (REPO_ROOT / "tmp" / "opencode-structured", "tmp/opencode-structured"),
        ]:
            for src in sorted(folder.rglob("*")):
                if not src.is_file() or _should_skip_tree_file(src):
                    continue
                arc = f"{prefix}/{src.relative_to(folder).as_posix()}"
                if _is_forbidden_in_inference_zip(arc):
                    raise RuntimeError(f"Forbidden reference-like path in inference bundle: {arc}")
                zf.write(src, arc)

        for src_rel, dst_arc in SMALL_OVERLAY_FILES:
            src = ollama_model_root / src_rel
            assert src.is_file(), f"Missing Ollama overlay file: {src}"
            zf.write(src, dst_arc)

    verify_inference_bundle(out_zip)
    return out_zip


def verify_inference_bundle(bundle_zip: Path) -> None:
    """Verify contents, pinned hashes, 30 shops, and zero reference leakage."""
    with zipfile.ZipFile(bundle_zip, "r") as zf:
        names = set(zf.namelist())
        for name in names:
            if _is_forbidden_in_inference_zip(name):
                raise AssertionError(f"Reference file leaked into inference bundle: {name}")

        required = [
            "data/train/questions.jsonl",
            "data/train/rulebook.md",
            "data/train/calendar.csv",
            "src/schemas.py",
            "src/eval/scorer.py",
            "tmp/opencode-structured/bridge.py",
            "tmp/opencode-structured/run.js",
            "tmp/opencode-structured/tools/inspect_table.js",
            "tmp/opencode-structured/tools/aggregate.js",
            "tmp/opencode-structured/tools/run_python.js",
            "tmp/opencode-structured/src/agent/sandbox.py",
            "ollama_pilot_overlay/manifests-v2/ollama.com/library/ornith15-datamate-pilot-8k/latest",
            "ollama_pilot_overlay/manifests/registry.ollama.ai/library/ornith15-datamate-pilot-8k/latest",
            "ollama_pilot_overlay/blobs/sha256-57ad8bec8adf0a704a07a26adb2abf9edae310ba0fd3cef575d02dac1af69bb5",
        ]
        for req in required:
            assert req in names, f"Missing {req} in {bundle_zip}"

        shops = {
            parts[3]
            for n in names
            if n.startswith("data/train/data/biz_") and len(parts := n.split("/")) >= 4
        }
        assert len(shops) == 30, f"Expected 30 shops, found {len(shops)}: {sorted(shops)}"

        sandbox_sha = hashlib.sha256(zf.read("tmp/opencode-structured/src/agent/sandbox.py")).hexdigest()
        assert sandbox_sha.startswith(EXPECTED_SANDBOX_PREFIX), f"Unexpected sandbox.py sha256: {sandbox_sha}"

        manifest_sha = hashlib.sha256(
            zf.read("ollama_pilot_overlay/manifests-v2/ollama.com/library/ornith15-datamate-pilot-8k/latest")
        ).hexdigest()
        assert manifest_sha == EXPECTED_MANIFEST_SHA256, f"Unexpected manifest sha256: {manifest_sha}"

    print(
        f"[OK] Verified inference bundle {bundle_zip.name}: "
        f"{bundle_zip.stat().st_size:,} bytes, 30 shops, sandbox={sandbox_sha[:12]}, manifest={manifest_sha[:12]}"
    )


def build_reference_bundle(out_zip: Path) -> Path:
    """Create Stage-2 score_only reference bundle."""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()

    files_to_pack = [
        (REPO_ROOT / "data" / "train" / "answers.jsonl", "data/train/answers.jsonl"),
        (REPO_ROOT / "eval_gold" / "unseen_gold_50.jsonl", "eval_gold/unseen_gold_50.jsonl"),
    ]
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for src, arc in files_to_pack:
            assert src.is_file(), f"Missing {src}"
            zf.write(src, arc)

    print(f"[OK] Built reference bundle {out_zip.name}: {out_zip.stat().st_size:,} bytes")
    return out_zip


def upload_to_hf(
    token: str,
    repo_id: str,
    inference_zip: Path,
    reference_zip: Path,
    ollama_model_root: Path,
    upload_zips: bool = True,
    upload_blobs: bool = True,
    repo_types: tuple[str, ...] = ("model", "dataset"),
) -> None:
    api = HfApi(token=token)

    if upload_zips:
        for repo_type in repo_types:
            api.upload_file(
                path_or_fileobj=str(inference_zip),
                path_in_repo=INFERENCE_BUNDLE_PATH_IN_REPO,
                repo_id=repo_id,
                repo_type=repo_type,
                commit_message="Upload Ornith+OpenCode inference bundle (strictly without answers/gold)",
            )
            print(f"[HF] Uploaded inference bundle -> {repo_type}:{repo_id}")

            api.upload_file(
                path_or_fileobj=str(reference_zip),
                path_in_repo="ornith_opencode_kaggle/ornith_opencode_reference_bundle.zip",
                repo_id=repo_id,
                repo_type=repo_type,
                commit_message="Upload Ornith+OpenCode Stage-2 score_only reference bundle",
            )
            print(f"[HF] Uploaded reference bundle -> {repo_type}:{repo_id}")

    if upload_blobs:
        for blob_name in LARGE_BLOB_NAMES:
            blob_path = ollama_model_root / "blobs" / blob_name
            assert blob_path.is_file(), f"Missing blob file: {blob_path}"
            for repo_type in repo_types:
                print(f"[HF] Uploading {blob_name} ({blob_path.stat().st_size:,} bytes) -> {repo_type}:{repo_id} ...")
                api.upload_file(
                    path_or_fileobj=str(blob_path),
                    path_in_repo=f"ornith_opencode_kaggle/ollama_blobs/{blob_name}",
                    repo_id=repo_id,
                    repo_type=repo_type,
                    commit_message=f"Upload Ornith 1.5 9B Q4_K_M Ollama blob {blob_name[:19]}",
                )
                print(f"[HF] Uploaded {blob_name} -> {repo_type}:{repo_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--ollama-model-root", type=Path, default=DEFAULT_OLLAMA_MODEL_ROOT)
    parser.add_argument("--staging-dir", type=Path, default=REPO_ROOT / "tmp" / "hf_staging")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--skip-blobs", action="store_true")
    parser.add_argument("--blobs-only", action="store_true")
    parser.add_argument("--repo-types", nargs="+", default=["model", "dataset"], choices=["model", "dataset"])
    args = parser.parse_args()

    inf_zip = args.staging_dir / "ornith_opencode_inference_bundle.zip"
    ref_zip = args.staging_dir / "ornith_opencode_reference_bundle.zip"
    if not args.blobs_only:
        inf_zip = build_inference_bundle(inf_zip, args.ollama_model_root)
        ref_zip = build_reference_bundle(ref_zip)

    if args.build_only:
        return

    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set HF_TOKEN in environment before uploading to Hugging Face.")
    upload_to_hf(
        token=token,
        repo_id=args.repo_id,
        inference_zip=inf_zip,
        reference_zip=ref_zip,
        ollama_model_root=args.ollama_model_root,
        upload_zips=not args.blobs_only,
        upload_blobs=not args.skip_blobs,
        repo_types=tuple(args.repo_types),
    )


if __name__ == "__main__":
    main()
