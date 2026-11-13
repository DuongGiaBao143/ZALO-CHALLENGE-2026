from pathlib import Path
import nbformat
import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = ROOT / "notebooks/Train_DeepSeek_R1_14B_Reasoning_Colab.ipynb"


def test_reasoning_colab_notebook_compiles_and_uses_r1_reasoning():
    assert NOTEBOOK_PATH.is_file(), f"Notebook not found: {NOTEBOOK_PATH}"
    nb = nbformat.read(str(NOTEBOOK_PATH), as_version=4)
    nbformat.validate(nb)

    code_cells = []
    for idx, cell in enumerate(nb.cells):
        if cell.cell_type == "code":
            code_cells.append(cell.source)
            compile(cell.source, f"<cell {idx}>", "exec")
            assert cell.outputs == []
            assert cell.execution_count is None

    all_code = "\n".join(code_cells)

    # 1. Completion format must be r1-reasoning
    assert "COMPLETION_FORMAT = 'r1-reasoning'" in all_code or "'--completion_format', 'r1-reasoning'" in all_code or "'--completion_format', COMP_FORMAT" in all_code

    # 2. Prompt format must be user-only
    assert "PROMPT_FORMAT = 'user-only'" in all_code

    # 3. References the 1,109 reasoning SFT dataset
    assert "deepseek_r1_1109_sft_train_ready.jsonl" in all_code

    # 4. Evaluates Base vs Reasoning SFT LoRA
    assert "BASE_REPORT = evaluate" in all_code
    assert "ADAPTER_REPORT = evaluate" in all_code
    assert "Reasoning SFT LoRA" in all_code
