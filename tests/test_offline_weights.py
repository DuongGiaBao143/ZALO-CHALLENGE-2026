"""Unit tests verifying offline model weight requirements and mocked engine imports."""

import json
import sys
from unittest.mock import MagicMock, patch
import pytest

from src.agent.solver import (
    DataMateAgent,
    TransformersBackend,
    VLLMBackend,
    _validate_local_model_directory,
    create_inference_backend,
)


def test_missing_local_model_dir_raises_without_calling_engine(tmp_path):
    """Proves that missing local weights directory raises FileNotFoundError before importing engine."""
    with patch.dict(sys.modules, {"vllm": MagicMock(), "transformers": MagicMock()}):
        # 1. Non-existent path
        with pytest.raises(FileNotFoundError, match="Offline model weights directory not found"):
            _validate_local_model_directory(str(tmp_path / "non_existent_model"))

        # 2. Exists but missing config.json
        empty_dir = tmp_path / "empty_model"
        empty_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="missing 'config.json'"):
            _validate_local_model_directory(str(empty_dir))

        # 3. Config present but missing tokenizer assets
        (empty_dir / "config.json").write_text("{}", encoding="utf-8")
        with pytest.raises(FileNotFoundError, match="missing tokenizer assets"):
            _validate_local_model_directory(str(empty_dir))

        # 4. Config and tokenizer present but missing weights
        (empty_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
        with pytest.raises(FileNotFoundError, match="no model weight files"):
            _validate_local_model_directory(str(empty_dir))

        # 5. Config, tokenizer, and minimal dummy weight file present -> passes presence check!
        (empty_dir / "model.safetensors").write_text("dummy", encoding="utf-8")
        validated_path = _validate_local_model_directory(str(empty_dir))
        assert validated_path.resolve() == empty_dir.resolve()

        # 6. Sharded index with missing shard raises
        sharded_dir = tmp_path / "sharded_model"
        sharded_dir.mkdir()
        (sharded_dir / "config.json").write_text("{}", encoding="utf-8")
        (sharded_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
        idx_content = {"weight_map": {"layer1": "model-00001-of-00002.safetensors"}}
        (sharded_dir / "model.safetensors.index.json").write_text(json.dumps(idx_content), encoding="utf-8")
        with pytest.raises(FileNotFoundError, match="was not found"):
            _validate_local_model_directory(str(sharded_dir))

        # 7. Sharded index with present shard passes
        (sharded_dir / "model-00001-of-00002.safetensors").write_text("dummy", encoding="utf-8")
        assert _validate_local_model_directory(str(sharded_dir)).resolve() == sharded_dir.resolve()


def test_invalid_dtype_fails_clearly(tmp_path):
    """Unsupported dtype values must raise ValueError."""
    fake_model_dir = tmp_path / "fake_model"
    fake_model_dir.mkdir()
    (fake_model_dir / "config.json").write_text("{}", encoding="utf-8")
    (fake_model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    (fake_model_dir / "model.safetensors").write_text("dummy", encoding="utf-8")

    with patch.dict(sys.modules, {"vllm": MagicMock()}):
        with pytest.raises(ValueError, match="Unsupported dtype"):
            VLLMBackend({"local_model_dir": str(fake_model_dir), "dtype": "int4_invalid"})

    with patch.dict(sys.modules, {"transformers": MagicMock(), "torch": MagicMock()}):
        with pytest.raises(ValueError, match="Unsupported dtype"):
            TransformersBackend({"local_model_dir": str(fake_model_dir), "dtype": "int4_invalid"})


def test_unknown_backend_fails_clearly():
    """Unsupported backend strings must raise ValueError."""
    with pytest.raises(ValueError, match="Unsupported model backend: 'flan_t5'"):
        create_inference_backend({"backend": "flan_t5"})


def test_transformers_enforces_token_budget(tmp_path):
    """Preserve the prompt and adapt completion budget to remaining context; reject a full prompt."""
    fake_dir = tmp_path / "budget_model"
    fake_dir.mkdir()
    (fake_dir / "config.json").write_text("{}", encoding="utf-8")
    (fake_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    (fake_dir / "model.safetensors").write_text("dummy", encoding="utf-8")

    mock_tokenizer = MagicMock()
    mock_tokenizer.apply_chat_template.return_value = "prompt text"
    # Mock return of tokenizer(prompt, return_tensors='pt'): input_ids shape (1, 1000)
    mock_inputs = MagicMock()
    mock_inputs.input_ids.shape = (1, 1000)
    mock_tokenizer.return_value = mock_inputs

    mock_model = MagicMock()
    mock_model.device = "cpu"
    mock_model.generate.return_value = [[0] * 1050]
    mock_tokenizer.decode.return_value = "generated answer"

    mock_torch = MagicMock()
    mock_transformers = MagicMock()
    mock_transformers.AutoTokenizer.from_pretrained.return_value = mock_tokenizer
    mock_transformers.AutoModelForCausalLM.from_pretrained.return_value = mock_model

    with patch.dict(sys.modules, {"transformers": mock_transformers, "torch": mock_torch}):
        # Keep all 1000 prompt tokens and reduce the completion cap from 500 to 200.
        backend = TransformersBackend({
            "local_model_dir": str(fake_dir),
            "max_model_len": 1200,
            "max_tokens": 500,
            "dtype": "float16",
            "max_generation_time_sec": 120,
        })
        assert backend.generate([{"role": "user", "content": "hello"}]) == 'generated answer'
        assert mock_model.generate.call_args.kwargs['max_new_tokens'] == 200
        assert mock_model.generate.call_args.kwargs['max_time'] == 120
        assert backend.max_tokens == 500

        # Budget = 2000, input = 1000, max_tokens = 500 -> 1000 + 500 = 1500 <= 2000 -> succeeds!
        backend_ok = TransformersBackend({
            "local_model_dir": str(fake_dir),
            "max_model_len": 2000,
            "max_tokens": 500,
            "dtype": "float16",
        })
        out = backend_ok.generate([{"role": "user", "content": "hello"}])
        assert out == "generated answer"
        assert mock_model.generate.call_args.kwargs['max_new_tokens'] == 500
        assert 'max_time' not in mock_model.generate.call_args.kwargs
        mock_model.generate.reset_mock()
        mock_inputs.input_ids.shape = (1, 2000)
        with pytest.raises(ValueError, match="Context budget exceeded"):
            backend_ok.generate([{"role": "user", "content": "hello"}])
        mock_model.generate.assert_not_called()
