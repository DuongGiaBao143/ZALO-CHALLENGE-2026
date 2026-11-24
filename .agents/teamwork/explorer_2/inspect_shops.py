from pathlib import Path
import re

def inspect_shops(base_dir, label):
    print(f"=== {label} ({base_dir}) ===")
    base = Path(base_dir)
    for p in sorted(base.glob("*/README.md")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        shop = p.parent.name
        files = [f.name for f in p.parent.glob("*") if f.name != "README.md"]
        # extract headers or keywords
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        # find domain hints: thuốc, cà phê, trà sữa, tạp hóa, vật liệu xây dựng, mẹ và bé, sửa xe, điện thoại
        hints = []
        for word in ["thuốc", "kê đơn", "hoạt chất", "cà phê", "trà sữa", "size", "topping", "vật liệu", "xi măng", "cát", "gạch", "sắt", "mẹ và bé", "sữa", "bỉm", "sửa xe", "nhớt", "thợ", "biển số", "điện thoại", "trả góp", "tạp hóa", "bách hóa"]:
            if re.search(r'\b' + re.escape(word) + r'\b', text, re.IGNORECASE):
                hints.append(word)
        print(f"{shop:8} | files: {len(files):2} | hints: {', '.join(set(hints))[:35]:35} | files: {', '.join(files)[:40]}")

inspect_shops("d:/PROJECT/ZALO-AI-CHALLENGE-2026/data/train/data", "TRAIN SET")
inspect_shops("d:/PROJECT/ZALO-AI-CHALLENGE-2026/data/public_test/data", "PUBLIC TEST SET")
