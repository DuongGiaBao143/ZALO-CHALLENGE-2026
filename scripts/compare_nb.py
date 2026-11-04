import json
import difflib

with open("result/kaggle_qwen7b_208_20261102/input_bundle/notebooks/02_train_sft_qwen7b_kaggle_2t4_208.ipynb", encoding="utf-8") as f:
    nb208 = json.load(f)

with open("notebooks/02_train_sft_qwen7b_kaggle_2t4_890.ipynb", encoding="utf-8") as f:
    nb890 = json.load(f)

for i, (c208, c890) in enumerate(zip(nb208["cells"], nb890["cells"])):
    s208 = "".join(c208["source"])
    s890 = "".join(c890["source"])
    if s208 != s890:
        print(f"=== Cell {i} changed ===")
        diff = difflib.unified_diff(s208.splitlines(keepends=True), s890.splitlines(keepends=True), fromfile="208", tofile="890")
        print("".join(diff))
