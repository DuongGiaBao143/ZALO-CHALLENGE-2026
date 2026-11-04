"""Package the minimal pilot bundle (code + 6 businesses + 30 pilot questions + tests + isolated gold)

for easy drag-and-drop upload to Google Colab.
"""

from __future__ import annotations

import os
from pathlib import Path
import zipfile


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    output_dir = project_root / "tmp"
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "datamate_pilot_bundle.zip"

    # Files and folders to include
    pilot_biz = ["biz_101", "biz_104", "biz_108", "biz_109", "biz_121", "biz_124"]

    include_patterns = [
        "src/**/*",
        "configs/**/*",
        "scripts/run_inference.py",
        "scripts/evaluate_local.py",
        "scripts/verify_submission.py",
        "tests/**/*",
        "eval_gold/pilot_gold_30.jsonl",
        "result/baseline_7b_pilot/pilot_questions_30.jsonl",
        "result/baseline_7b_pilot/sampling_manifest.json",
        "data/train/rulebook.md",
        "data/train/calendar.csv",
    ]

    for b in pilot_biz:
        include_patterns.append(f"data/train/data/{b}/**/*")

    print(f"Creating bundle zip at: {zip_path}")
    count = 0
    total_uncompressed_bytes = 0

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        added_paths = set()
        for pattern in include_patterns:
            for file_path in project_root.glob(pattern):
                if file_path.is_file():
                    # Exclude pycache and test results
                    if "__pycache__" in file_path.parts or file_path.suffix == ".pyc":
                        continue
                    if "result" in file_path.parts and file_path.name.endswith(".log"):
                        continue

                    rel_path = file_path.relative_to(project_root)
                    rel_str = str(rel_path).replace("\\", "/")
                    if rel_str not in added_paths:
                        zf.write(file_path, arcname=rel_str)
                        added_paths.add(rel_str)
                        count += 1
                        total_uncompressed_bytes += file_path.stat().st_size

    zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
    raw_size_mb = total_uncompressed_bytes / (1024 * 1024)
    print(f"Packaged {count} files.")
    print(f"Uncompressed size: {raw_size_mb:.2f} MB")
    print(f"Zip bundle size: {zip_size_mb:.2f} MB")
    print("Bundle created successfully!")


if __name__ == "__main__":
    main()
