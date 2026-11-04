import os
import sys
import json
import shutil
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_sft_dataset import build_sft_dataset
BUNDLE_DIR = ROOT / "result" / "kaggle_qwen7b_890_input_bundle"
BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

# 1. Directories
(BUNDLE_DIR / "configs").mkdir(exist_ok=True)
(BUNDLE_DIR / "dataset").mkdir(exist_ok=True)
(BUNDLE_DIR / "docs").mkdir(exist_ok=True)
(BUNDLE_DIR / "notebooks").mkdir(exist_ok=True)
(BUNDLE_DIR / "scripts").mkdir(exist_ok=True)
(BUNDLE_DIR / "src" / "coder_training").mkdir(parents=True, exist_ok=True)

# 2. Copy dataset
dataset_src = ROOT / "verified_sft_dataset.jsonl"
dataset_dst = BUNDLE_DIR / "dataset" / "sft_train_ready.jsonl"
build_sft_dataset(str(dataset_src), str(ROOT / 'data/train'), str(dataset_dst))

# Calculate SHA256 of dataset
dataset_sha256 = hashlib.sha256(dataset_dst.read_bytes()).hexdigest()
print(f"Dataset copied. SHA256: {dataset_sha256}")

# 3. Copy configs and requirements
shutil.copy2(ROOT / "configs" / "accelerate_kaggle_2t4_sft.yaml", BUNDLE_DIR / "configs" / "accelerate_kaggle_2t4_sft.yaml")
shutil.copy2(ROOT / "requirements-kaggle-sft.txt", BUNDLE_DIR / "requirements-kaggle-sft.txt")

# 4. Copy scripts
shutil.copy2(ROOT / "scripts" / "train_sft_kaggle_2t4.py", BUNDLE_DIR / "scripts" / "train_sft_kaggle_2t4.py")
shutil.copy2(ROOT / "scripts" / "train_sft_lora.py", BUNDLE_DIR / "scripts" / "train_sft_lora.py")
shutil.copy2(ROOT / "scripts" / "build_sft_dataset.py", BUNDLE_DIR / "scripts" / "build_sft_dataset.py")
shutil.copy2(ROOT / "scripts" / "evaluate_pilot_30.py", BUNDLE_DIR / "scripts" / "evaluate_pilot_30.py")
shutil.copy2(ROOT / "scripts" / "watch_kaggle_sft.ps1", BUNDLE_DIR / "scripts" / "watch_kaggle_sft.ps1")

# 5. Copy src/coder_training
for py_file in (ROOT / "src").rglob("*.py"):
    target = BUNDLE_DIR / py_file.relative_to(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(py_file, target)

# 6. Generate docs/KAGGLE_QWEN7B_890.md
doc_content = f"""# Qwen7B SFT với 890 mẫu trên Kaggle 2×T4

Notebook: `notebooks/02_train_sft_qwen7b_kaggle_2t4_890.ipynb`.

1. Upload gói `datamate_qwen7b_890_kaggle_input.zip` thành **private Kaggle Dataset**, rồi Add Input vào notebook.
2. Import notebook `.ipynb`. Chọn GPU **T4 ×2**, bật Internet để cài dependencies và gắn weights **Qwen2.5-Coder-7B-Instruct** qua Add Input.
3. Dataset gồm 890 mẫu chuẩn hóa (SHA256: {dataset_sha256}), phủ 24 doanh nghiệp.
"""
(BUNDLE_DIR / "docs" / "KAGGLE_QWEN7B_890.md").write_text(doc_content, encoding="utf-8")

# 7. Generate updated notebook: notebooks/02_train_sft_qwen7b_kaggle_2t4_890.ipynb
old_nb_path = ROOT / "result" / "kaggle_qwen7b_208_20261102" / "input_bundle" / "notebooks" / "02_train_sft_qwen7b_kaggle_2t4_208.ipynb"
with open(old_nb_path, "r", encoding="utf-8") as f:
    nb = json.load(f)

# Update notebook contents
for cell in nb["cells"]:
    src = "".join(cell.get("source", []))
    # Replace references to 208 with 890
    src = src.replace("208 mẫu", "890 mẫu")
    src = src.replace("datamate_qwen7b_208", "datamate_qwen7b_890")
    src = src.replace("RUN_NAME = 'qwen7b_208_fp16_lora'", "RUN_NAME = 'qwen7b_890_fp16_lora'")
    src = src.replace("cfa70a9af1b87d282ff5428c7bf7afd9a3308a449a2095d23b320479284fd8fc", dataset_sha256)
    src = src.replace("datamate-qwen7b-sft208-2t4", "datamate-qwen7b-sft890-2t4")
    src = src.replace("len(records) == 208 and len({row['id'] for row in records}) == 208", "len(records) == 890 and len({row['id'] for row in records}) == 890")
    src = src.replace("assert report['records'] == 208 and not report['overlength']", "assert report['records'] == 890 and not report['overlength']")
    src = src.replace("NCCL_IB_DISABLE='1', OMP_NUM_THREADS='2', PYTHONUNBUFFERED='1')", "NCCL_IB_DISABLE='1', OMP_NUM_THREADS='2', PYTHONUNBUFFERED='1', PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')")
    src = src.replace("Đủ 208 mẫu", "Đủ 890 mẫu")
    src = src.replace("NCCL_IB_DISABLE='1', OMP_NUM_THREADS='2', PYTHONUNBUFFERED='1')", "NCCL_IB_DISABLE='1', OMP_NUM_THREADS='2', PYTHONUNBUFFERED='1', PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')")
    src = src.replace("Đủ 208 mẫu", "Đủ 890 mẫu")
    # Split back into lines
    lines = [line + "\n" for line in src.split("\n")]
    if lines and lines[-1] == "\n":
        lines.pop()
    cell["source"] = lines

# Save notebook inside bundle and in repo notebooks/
new_nb_path_bundle = BUNDLE_DIR / "notebooks" / "02_train_sft_qwen7b_kaggle_2t4_890.ipynb"
with open(new_nb_path_bundle, "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)

repo_nb_path = ROOT / "notebooks" / "02_train_sft_qwen7b_kaggle_2t4_890.ipynb"
repo_nb_path.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(new_nb_path_bundle, repo_nb_path)

# 8. Create bundle_manifest.json
manifest_files = {}
for file_path in sorted(BUNDLE_DIR.rglob("*")):
    if file_path.is_file() and file_path.name != "bundle_manifest.json":
        rel = file_path.relative_to(BUNDLE_DIR).as_posix()
        manifest_files[rel] = hashlib.sha256(file_path.read_bytes()).hexdigest()

manifest = {
    "bundle": "datamate-qwen7b-sft890-2t4",
    "dataset_sha256": dataset_sha256,
    "rows": 890,
    "files": manifest_files,
    "revision": "hub-backup-v1"
}
with open(BUNDLE_DIR / "bundle_manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)

print("Generated bundle_manifest.json with", len(manifest_files), "files")

# 9. Create Zips
# A) Complete Kaggle Input Bundle
zip_bundle_path = ROOT / "datamate_qwen7b_890_kaggle_input.zip"
if zip_bundle_path.exists():
    zip_bundle_path.unlink()

shutil.make_archive(str(ROOT / "datamate_qwen7b_890_kaggle_input"), "zip", BUNDLE_DIR)
print(f"Created bundle zip: {zip_bundle_path} ({zip_bundle_path.stat().st_size:,} bytes)")

# B) Standalone SFT Dataset Zip
zip_dataset_path = ROOT / "verified_sft_dataset_890.zip"
import zipfile
with zipfile.ZipFile(zip_dataset_path, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.write(dataset_src, arcname="verified_sft_dataset.jsonl")
    zf.write(dataset_dst, arcname="sft_train_ready.jsonl")
print(f"Created standalone dataset zip: {zip_dataset_path} ({zip_dataset_path.stat().st_size:,} bytes)")

# 10. Copy both zips and new notebook to Google Drive as well
DRIVE_DIR = Path(r"G:\My Drive\Colab Notebooks\ZALO-AI-CHALLENGE-2026")
if DRIVE_DIR.exists():
    shutil.copy2(zip_bundle_path, DRIVE_DIR / "datamate_qwen7b_890_kaggle_input.zip")
    shutil.copy2(zip_dataset_path, DRIVE_DIR / "verified_sft_dataset_890.zip")
    shutil.copy2(repo_nb_path, DRIVE_DIR / "notebooks" / "02_train_sft_qwen7b_kaggle_2t4_890.ipynb")
    print("Also synced zips and notebook to Google Drive!")
