import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import generate_sft_vllm as generator


class TestCodeGeneration(unittest.TestCase):
    def test_skips_existing_and_holdout_then_exports_verified_compact_code(self):
        reply = '''```python
df = pd.read_csv(os.path.join(BUSINESS_DIR, "sales.csv"))
print(json.dumps({"kind":"final","type":"number","answer":int(df.amount.sum()),"evidence":"sales.csv"}))
```'''

        class Engine:
            def __init__(self, **kwargs):
                assert kwargs["tensor_parallel_size"] == 2
                assert kwargs["enable_lora"]

            def generate(self, prompts, params, **kwargs):
                assert len(prompts) == 1 and "New question" in prompts[0]
                assert "lora_request" in kwargs
                return [SimpleNamespace(outputs=[SimpleNamespace(text=reply, finish_reason="stop")])]

        tokenizer = SimpleNamespace(
            apply_chat_template=lambda messages, **kw: "\n".join(m["content"] for m in messages),
            encode=lambda text: text.split(),
        )
        modules = {
            "python_calamine": SimpleNamespace(),
            "transformers": SimpleNamespace(AutoTokenizer=SimpleNamespace(from_pretrained=lambda *a, **kw: tokenizer)),
            "vllm": SimpleNamespace(LLM=Engine, SamplingParams=lambda **kw: kw),
            "vllm.lora.request": SimpleNamespace(LoRARequest=lambda *a: a),
        }
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            train = root / "data/train"
            shop = train / "data/biz_fixture"
            shop.mkdir(parents=True)
            (shop / "sales.csv").write_text("amount\n10\n20\n", encoding="utf-8")

            def write_rows(path, rows):
                path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

            questions = [
                dict(id=qid, business_id=shop.name, as_of_date="2026-08-19", question=question)
                for qid, question in (("old", "Old question"), ("hold", "Holdout"), ("new", "New question"))
            ]
            write_rows(train / "questions.jsonl", questions)
            write_rows(train / "answers.jsonl", [dict(id=q["id"], type="number", answer=30) for q in questions])
            write_rows(root / "seed.jsonl", [{"id": "old"}])
            write_rows(root / "holdout.jsonl", [{"id": "hold"}])
            (root / "adapter").mkdir()
            argv = ["generate_sft_vllm.py", "--backend", "vllm", "--tp", "2",
                    "--lora-adapter", str(root / "adapter"), "--output-dir", str(root / "out"),
                    "--drive-backup-dir", str(root / "missing/backup"),
                    "--exclude-dataset", str(root / "seed.jsonl"),
                    "--exclude-dataset", str(root / "holdout.jsonl"),
                    "--max-samples", "1", "--compact-output"]
            with patch.dict(sys.modules, modules), patch.object(sys, "argv", argv), \
                    patch.object(generator, "PROJECT_ROOT", root), patch.object(generator, "version", return_value="test"):
                generator.main()
            result = root / "out/verified_compact_dataset.jsonl"
            row = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(set(row), {"id", "business_id", "code"})
            self.assertEqual(row["id"], "new")
            self.assertIn("sales.csv", row["code"])


if __name__ == "__main__":
    unittest.main()
