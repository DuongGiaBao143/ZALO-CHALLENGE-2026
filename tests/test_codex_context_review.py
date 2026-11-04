"""Independent checks for observed context bloat and offline packaging gaps."""
import sys
from types import SimpleNamespace

import pytest

from src.agent.solver import TransformersBackend, VLLMBackend
from src.profiler.business_loader import format_profile_for_prompt
from src.schemas import BusinessProfile, TableSchema


def test_compact_profile_keeps_all_schemas_and_omits_bulky_values(tmp_path):
    huge_value = "BULKY_SAMPLE_SENTINEL" * 5000
    tables = [TableSchema(source_file=f"file_{i}.xlsx", table_name=f"sheet_{i}",
                          columns=["order_id", "status"], dtypes={"order_id": "object", "status": "object"},
                          row_count=100, sample_rows=[{"order_id": huge_value}],
                          categorical_values={"status": [huge_value]}, raw_preview=[[huge_value]]) for i in range(20)]
    profile = BusinessProfile("shop", str(tmp_path), "FULL_README_MARKER", tables=tables,
                              files=[f"file_{i}.xlsx" for i in range(20)])
    compact = format_profile_for_prompt(profile, compact=True)
    assert len(compact) < 20000
    assert "BULKY_SAMPLE_SENTINEL" not in compact
    assert "FULL_README_MARKER" in compact
    for i in range(20):
        assert f"file_{i}.xlsx" in compact and f"sheet_{i}" in compact
    assert "order_id" in compact and "status" in compact


def test_config_only_directory_is_not_a_packaged_model(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text('{"model_type":"qwen2"}', encoding="utf-8")
    engine_calls = []
    monkeypatch.setitem(sys.modules, "vllm", SimpleNamespace(LLM=lambda **kw: engine_calls.append(kw), SamplingParams=lambda **kw: kw))
    with pytest.raises(FileNotFoundError):
        VLLMBackend({"local_model_dir": str(tmp_path)})
    assert not engine_calls


def test_partial_sharded_checkpoint_is_checked_even_when_one_weight_file_exists(tmp_path):
    import json
    from src.agent.solver import _validate_local_model_directory

    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (tmp_path / "model-00001-of-00002.safetensors").write_bytes(b"dummy shard")
    index = {"weight_map": {"layer_a": "model-00001-of-00002.safetensors", "layer_b": "model-00002-of-00002.safetensors"}}
    (tmp_path / "model.safetensors.index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        _validate_local_model_directory(str(tmp_path))


def test_transformers_refuses_input_plus_output_over_context_limit():
    import torch

    class Encoding(dict):
        @property
        def input_ids(self):
            return self["input_ids"]

        def to(self, device):
            return self

    class Tokenizer:
        eos_token_id = 0

        def apply_chat_template(self, *args, **kwargs):
            return "ORIGINAL_QUESTION_AND_RULEBOOK"

        def __call__(self, *args, **kwargs):
            assert not kwargs.get("truncation"), "Never silently truncate question/rulebook."
            return Encoding(input_ids=torch.ones((1, 10), dtype=torch.long))

    class Model:
        device = "cpu"

        def generate(self, **kwargs):
            raise AssertionError("Model must not run when the prompt fills the entire context budget.")

    backend = object.__new__(TransformersBackend)
    backend.tokenizer = Tokenizer()
    backend.model = Model()
    backend.max_tokens = 2
    backend.max_model_len = 10
    backend.temperature = 0.0
    with pytest.raises(ValueError):
        backend.generate([{"role": "user", "content": "ORIGINAL_QUESTION_AND_RULEBOOK"}])
