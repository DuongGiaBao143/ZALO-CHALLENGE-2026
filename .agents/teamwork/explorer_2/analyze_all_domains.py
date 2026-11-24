import os
import re
from pathlib import Path
import json

def get_shop_details(base_dir):
    base = Path(base_dir)
    results = []
    for shop_dir in sorted(base.glob('*')):
        if not shop_dir.is_dir():
            continue
        readme_file = shop_dir / "README.md"
        readme_text = readme_file.read_text(encoding='utf-8', errors='ignore') if readme_file.exists() else ""
        
        # files
        files = [f.name for f in shop_dir.glob('*') if f.name != 'README.md']
        exts = set(f.split('.')[-1].lower() for f in files)
        
        # detect domain
        text_lower = readme_text.lower()
        domain = "Unknown"
        if any(k in text_lower for k in ["thuốc", "kê đơn", "hoạt chất", "dược"]):
            domain = "Nhà thuốc"
        elif any(k in text_lower for k in ["sửa xe", "nhớt", "thợ", "lượt xe", "biển số"]):
            domain = "Sửa xe"
        elif any(k in text_lower for k in ["mẹ và bé", "sữa", "bỉm"]):
            domain = "Mẹ và bé"
        elif any(k in text_lower for k in ["điện thoại", "trả góp", "thu máy cũ", "imei"]):
            domain = "Điện thoại"
        elif any(k in text_lower for k in ["vật liệu", "xi măng", "gạch", "cát", "sắt"]):
            domain = "Vật liệu xây dựng"
        elif any(k in text_lower for k in ["cà phê", "trà sữa", "topping", "size m", "size l"]):
            domain = "Cà phê / Trà sữa"
        elif any(k in text_lower for k in ["tạp hóa", "bách hóa", "chợ"]):
            domain = "Tạp hóa"
        else:
            # check files or readme content
            if "pos.sqlite" in files:
                domain = "POS Tổng hợp / Tạp hóa"
            else:
                domain = "Tạp hóa / Bán lẻ tổng hợp"
                
        results.append({
            "shop": shop_dir.name,
            "domain": domain,
            "exts": list(exts),
            "num_files": len(files),
            "files": files[:3],
            "readme_len": len(readme_text.splitlines())
        })
    return results

print("=== TRAIN SHOPS ===")
train_res = get_shop_details("d:/PROJECT/ZALO-AI-CHALLENGE-2026/data/train/data")
for r in train_res:
    print(f"{r['shop']} | Domain: {r['domain']:20} | Exts: {r['exts']} | Files: {r['num_files']} | Sample: {r['files']}")

print("\n=== PUBLIC TEST SHOPS ===")
test_res = get_shop_details("d:/PROJECT/ZALO-AI-CHALLENGE-2026/data/public_test/data")
for r in test_res:
    print(f"{r['shop']} | Domain: {r['domain']:20} | Exts: {r['exts']} | Files: {r['num_files']} | Sample: {r['files']}")
