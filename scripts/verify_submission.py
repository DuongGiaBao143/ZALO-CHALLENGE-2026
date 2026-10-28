#!/usr/bin/env python3
"""Pre-submission sanity checker for `submission.jsonl` before uploading to Zalo AI Portal."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.schemas import VALID_ANSWER_TYPES


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify submission.jsonl format and completeness.")
    parser.add_argument("--submission", type=Path, required=True, help="Path to submission.jsonl")
    parser.add_argument(
        "--questions",
        type=Path,
        default=None,
        help="Optional path to questions.jsonl to verify ID alignment.",
    )
    args = parser.parse_args()

    if not args.submission.exists():
        print(f"[ERROR] File not found: {args.submission}")
        sys.exit(1)

    seen_ids = set()
    type_counts = Counter()
    errors = []

    with args.submission.open("r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                errors.append(f"Line {line_no}: Empty line is not allowed.")
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"Line {line_no}: Invalid JSON ({exc})")
                continue

            qid = obj.get("id")
            qtype = obj.get("type")
            if not qid or not isinstance(qid, str):
                errors.append(f"Line {line_no}: Missing or invalid 'id'.")
            elif qid in seen_ids:
                errors.append(f"Line {line_no}: Duplicate id '{qid}'.")
            else:
                seen_ids.add(qid)

            if qtype not in VALID_ANSWER_TYPES:
                errors.append(f"Line {line_no} (id={qid}): Invalid type '{qtype}'.")
            else:
                type_counts[qtype] += 1

    if args.questions and args.questions.exists():
        expected_ids = set()
        with args.questions.open("r", encoding="utf-8") as qf:
            for line in qf:
                if line.strip():
                    expected_ids.add(json.loads(line)["id"])
        missing = expected_ids - seen_ids
        extra = seen_ids - expected_ids
        if missing:
            errors.append(f"Missing {len(missing)} question IDs (e.g. {list(missing)[:5]}).")
        if extra:
            errors.append(f"Found {len(extra)} unexpected question IDs (e.g. {list(extra)[:5]}).")

    print("=" * 60)
    print(f"Submission File : {args.submission}")
    print(f"SHA256 Checksum : {sha256_file(args.submission)}")
    print(f"Total Valid IDs : {len(seen_ids)}")
    print("Type Distribution:")
    for t, cnt in sorted(type_counts.items()):
        print(f"  - {t:<14}: {cnt}")
    print("=" * 60)

    if errors:
        print(f"[FAILED] Found {len(errors)} error(s):")
        for err in errors[:20]:
            print(f"  * {err}")
        sys.exit(1)
    else:
        print("[OK] submission.jsonl passed all format checks!")


if __name__ == "__main__":
    main()
