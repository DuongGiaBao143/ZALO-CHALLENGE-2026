"""Unit tests exercising the multi-turn DataMateAgent with ScriptedBackend and real synthetic CSV."""

import json
from pathlib import Path
import pandas as pd
import pytest

from src.agent.solver import (
    DataMateAgent,
    ScriptedBackend,
    resolve_business_path,
)
from src.schemas import AnswerType, QuestionItem


@pytest.fixture
def synthetic_split(tmp_path):
    """Create a minimal synthetic split with rulebook, calendar, and a test shop."""
    split_dir = tmp_path / "mock_split"
    split_dir.mkdir()

    # Shared rulebook and calendar
    rulebook = split_dir / "rulebook.md"
    rulebook.write_text("# Test Rulebook\nDoanh thu tính bằng tổng số tiền.", encoding="utf-8")

    calendar = split_dir / "calendar.csv"
    calendar.write_text("solar_date,lunar_date,holiday\n2026-08-27,2026-07-15,false\n", encoding="utf-8")

    # Business data/<business_id>
    biz_dir = split_dir / "data" / "biz_001"
    biz_dir.mkdir(parents=True)

    readme = biz_dir / "README.md"
    readme.write_text("Tiệm bánh mì. Lưu trữ trong banh_mi.csv.", encoding="utf-8")

    # Synthetic sales data
    df = pd.DataFrame({
        "ma_don": ["DH1", "DH2", "DH3"],
        "ngay": ["2026-08-27", "2026-08-27", "2026-08-26"],
        "so_luong": [2, 3, 5],
        "tien": [40000, 60000, 100000],
        "trang_thai": ["thanh_cong", "da_huy", "thanh_cong"],
    })
    df.to_csv(biz_dir / "banh_mi.csv", index=False)

    return split_dir


class TestMultiTurnSolver:
    def test_observation_then_final_on_synthetic_data(self, synthetic_split):
        """Turn 1 emits observation, Turn 2 uses observation to emit final answer."""
        config = {
            "agent": {"max_turns": 3, "max_code_executions": 3, "sandbox_timeout_sec": 5},
            "paths": {"work_dir": str(synthetic_split / "work")},
        }

        # Turn 1: observation exploring columns of banh_mi.csv
        turn1_code = (
            "```python\n"
            "import os, json, pandas as pd\n"
            "df = pd.read_csv(os.path.join(BUSINESS_DIR, 'banh_mi.csv'))\n"
            "print(json.dumps({'kind': 'observation', 'data': {'cols': list(df.columns)}, 'message': 'found cols'}))\n"
            "```"
        )
        # Turn 2: final calculation of revenue on 2026-08-27 for thanh_cong orders (40000)
        turn2_code = (
            "```python\n"
            "import os, json, pandas as pd\n"
            "df = pd.read_csv(os.path.join(BUSINESS_DIR, 'banh_mi.csv'))\n"
            "rev = int(df[(df['ngay'] == '2026-08-27') & (df['trang_thai'] == 'thanh_cong')]['tien'].sum())\n"
            "print(json.dumps({'kind': 'final', 'type': 'number', 'answer': rev, 'evidence': 'banh_mi.csv: order DH1'}))\n"
            "```"
        )

        backend = ScriptedBackend([turn1_code, turn2_code])
        agent = DataMateAgent(config=config, data_dir=synthetic_split, backend=backend)

        q_item = QuestionItem(
            id="q_test_1",
            business_id="biz_001",
            question="Doanh thu ngày hôm nay là bao nhiêu?",
            as_of_date="2026-08-27",
        )
        sub_item, trace = agent.answer_question_with_trace(q_item)

        assert sub_item.type == AnswerType.NUMBER.value
        assert sub_item.answer == 40000
        assert len(trace["attempts"]) == 2
        assert trace["attempts"][0]["kind"] == "observation"
        assert trace["attempts"][1]["kind"] == "final"

    def test_execution_error_then_correction_then_final(self, synthetic_split):
        """Turn 1 has runtime KeyError, Turn 2 corrects column name and succeeds."""
        config = {
            "agent": {"max_turns": 3, "max_code_executions": 3, "sandbox_timeout_sec": 5},
            "paths": {"work_dir": str(synthetic_split / "work")},
        }

        # Turn 1: KeyError on non-existent column 'doanh_thu'
        turn1_code = (
            "```python\n"
            "import os, json, pandas as pd\n"
            "df = pd.read_csv(os.path.join(BUSINESS_DIR, 'banh_mi.csv'))\n"
            "val = df['doanh_thu'].sum()\n"
            "print(json.dumps({'kind': 'final', 'type': 'number', 'answer': val, 'evidence': 'banh_mi.csv'}))\n"
            "```"
        )
        # Turn 2: Corrects to 'tien' column
        turn2_code = (
            "```python\n"
            "import os, json, pandas as pd\n"
            "df = pd.read_csv(os.path.join(BUSINESS_DIR, 'banh_mi.csv'))\n"
            "val = int(df['tien'].sum())\n"
            "print(json.dumps({'kind': 'final', 'type': 'number', 'answer': val, 'evidence': 'banh_mi.csv: sum of tien'}))\n"
            "```"
        )

        backend = ScriptedBackend([turn1_code, turn2_code])
        agent = DataMateAgent(config=config, data_dir=synthetic_split, backend=backend)

        q_item = QuestionItem(
            id="q_test_2",
            business_id="biz_001",
            question="Tổng tiền tất cả đơn hàng là bao nhiêu?",
            as_of_date="2026-08-27",
        )
        sub_item, trace = agent.answer_question_with_trace(q_item)

        assert sub_item.type == AnswerType.NUMBER.value
        assert sub_item.answer == 200000
        assert len(trace["attempts"]) == 2
        assert trace["attempts"][0]["success"] is False
        assert trace["attempts"][1]["success"] is True

    def test_invalid_final_type_corrected_within_budget(self, synthetic_split):
        """Turn 1 emits non-numeric answer for number type, Turn 2 fixes it."""
        config = {
            "agent": {"max_turns": 3, "max_code_executions": 3, "sandbox_timeout_sec": 5},
            "paths": {"work_dir": str(synthetic_split / "work")},
        }

        # Turn 1: invalid string "hai trăm ngàn" for type number
        turn1_code = (
            "```python\n"
            "import json\n"
            "print(json.dumps({'kind': 'final', 'type': 'number', 'answer': 'hai trăm ngàn', 'evidence': 'synthetic'}))\n"
            "```"
        )
        # Turn 2: properly formatted integer
        turn2_code = (
            "```python\n"
            "import json\n"
            "print(json.dumps({'kind': 'final', 'type': 'number', 'answer': 200000, 'evidence': 'synthetic'}))\n"
            "```"
        )

        backend = ScriptedBackend([turn1_code, turn2_code])
        agent = DataMateAgent(config=config, data_dir=synthetic_split, backend=backend)

        q_item = QuestionItem(
            id="q_test_3",
            business_id="biz_001",
            question="Tổng tiền?",
            as_of_date="2026-08-27",
        )
        sub_item, trace = agent.answer_question_with_trace(q_item)

        assert sub_item.type == AnswerType.NUMBER.value
        assert sub_item.answer == 200000

    def test_exhausted_observations_fall_back_to_abstain(self, synthetic_split):
        """Model outputs observations on all 3 turns -> abstains on final turn."""
        config = {
            "agent": {"max_turns": 3, "max_code_executions": 3, "sandbox_timeout_sec": 5},
            "paths": {"work_dir": str(synthetic_split / "work")},
        }

        obs_code = (
            "```python\n"
            "import json\n"
            "print(json.dumps({'kind': 'observation', 'data': [1, 2, 3], 'message': 'still looking'}))\n"
            "```"
        )
        backend = ScriptedBackend([obs_code, obs_code, obs_code])
        agent = DataMateAgent(config=config, data_dir=synthetic_split, backend=backend)

        q_item = QuestionItem(
            id="q_test_4",
            business_id="biz_001",
            question="Một câu hỏi chưa thể trả lời",
            as_of_date="2026-08-27",
        )
        sub_item, trace = agent.answer_question_with_trace(q_item)

        assert sub_item.type == AnswerType.ABSTAIN.value
        assert sub_item.answer is None
        assert len(trace["attempts"]) == 3

    def test_distinguish_legitimate_zero_vs_unanswerable(self, synthetic_split):
        """Legitimate zero count must return number 0, not unanswerable."""
        config = {
            "agent": {"max_turns": 3, "max_code_executions": 3, "sandbox_timeout_sec": 5},
            "paths": {"work_dir": str(synthetic_split / "work")},
        }

        # Case A: Legitimate zero (e.g. orders on 2026-08-25 = 0)
        zero_code = (
            "```python\n"
            "import os, json, pandas as pd\n"
            "df = pd.read_csv(os.path.join(BUSINESS_DIR, 'banh_mi.csv'))\n"
            "cnt = int((df['ngay'] == '2026-08-25').sum())\n"
            "print(json.dumps({'kind': 'final', 'type': 'number', 'answer': cnt, 'evidence': 'banh_mi.csv: 0 matching rows'}))\n"
            "```"
        )
        backend = ScriptedBackend([zero_code])
        agent = DataMateAgent(config=config, data_dir=synthetic_split, backend=backend)

        q_item = QuestionItem(
            id="q_zero",
            business_id="biz_001",
            question="Có bao nhiêu đơn ngày 2026-08-25?",
            as_of_date="2026-08-27",
        )
        sub_item, _ = agent.answer_question_with_trace(q_item)
        assert sub_item.type == AnswerType.NUMBER.value
        assert sub_item.answer == 0

        # Case B: Confirmed missing evidence (cost data missing) -> unanswerable with required reason
        unans_code = (
            "```python\n"
            "import json\n"
            "print(json.dumps({'kind': 'final', 'type': 'unanswerable', 'answer': None, 'evidence': 'inspected banh_mi.csv: no cost column', 'reason': 'Không có dữ liệu giá vốn'}))\n"
            "```"
        )
        agent.backend = ScriptedBackend([unans_code])
        q_unans = QuestionItem(
            id="q_unans",
            business_id="biz_001",
            question="Lợi nhuận gộp là bao nhiêu?",
            as_of_date="2026-08-27",
        )
        sub_unans, _ = agent.answer_question_with_trace(q_unans)
        assert sub_unans.type == AnswerType.UNANSWERABLE.value
        assert sub_unans.answer is None
        assert sub_unans.reason == "Không có dữ liệu giá vốn"

    def test_path_traversal_strictly_rejected(self, synthetic_split):
        """Traversal attempts like '../secret' or invalid characters are rejected."""
        with pytest.raises(ValueError, match="Path traversal or invalid characters"):
            resolve_business_path(synthetic_split, "../secret")

        with pytest.raises(ValueError, match="Path traversal or invalid characters"):
            resolve_business_path(synthetic_split, "/etc/passwd")

        with pytest.raises(ValueError, match="Path traversal or invalid characters"):
            resolve_business_path(synthetic_split, "biz_001; rm -rf")

    def test_unsupported_backend_and_missing_weights_fail_clearly(self, synthetic_split):
        """Unsupported backend raises ValueError; vllm/transformers with non-existent path raises."""
        with pytest.raises(ValueError, match="Unsupported model backend: 'invalid_backend'"):
            DataMateAgent(
                config={"model": {"backend": "invalid_backend"}},
                data_dir=synthetic_split,
            )

        with pytest.raises(FileNotFoundError):
            DataMateAgent(
                config={"model": {"backend": "transformers", "local_model_dir": "/non/existent/model"}},
                data_dir=synthetic_split,
            )
