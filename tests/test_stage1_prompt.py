"""Stage 1 uses folder/README/schema input and preserves distinct table schemas."""

import json
from pathlib import Path

from src.profiler.business_loader import format_profile_for_prompt
from src.schemas import BusinessProfile, TableSchema


def test_schema_groups_identical_sheets_but_keeps_dtype_header_and_error_differences():
    tables = [
        TableSchema('sales.xlsx', name, ['id', 'amount'], {'id': 'object', 'amount': dtype}, 100,
                    sample_rows=[{'id': 'SAMPLE_NOT_FOR_PROMPT'}],
                    categorical_values={'id': ['ENUM_NOT_FOR_PROMPT']},
                    candidate_header_row=header, header_uncertainty=header != 0)
        for name, dtype, header in [('Jan', 'int64', 0), ('Feb', 'int64', 0),
                                    ('Mar', 'object', 0), ('Apr', 'int64', 2)]
    ]
    tables.append(TableSchema('broken.csv', 'broken', [], {}, 0, status='error', error_message='decode failed'))
    profile = BusinessProfile('shop', '/business/shop', 'README rule: one box has 24 bottles.',
                              tables=tables, files=['sales.xlsx', 'broken.csv'])
    prompt = format_profile_for_prompt(profile, compact=True)
    assert '/business/shop' not in prompt and profile.readme_text in prompt
    assert 'BUSINESS_DIR' in prompt
    assert 'Jan, Feb' in prompt
    assert '`amount`: int64' in prompt and '`amount`: object' in prompt
    assert 'Apr' in prompt and 'header=2' in prompt
    assert 'broken.csv' in prompt and 'decode failed' in prompt
    assert 'SAMPLE_NOT_FOR_PROMPT' not in prompt and 'ENUM_NOT_FOR_PROMPT' not in prompt


def test_stage1_notebook_uses_new_output_and_context_mode():
    root = Path(__file__).resolve().parents[1]
    nb = json.loads((root / 'notebooks/01_generate_sft_dataset_qwen7b.ipynb').read_text(encoding='utf-8'))
    code = next(''.join(c['source']) for c in nb['cells']
                if c['cell_type'] == 'code' and "'--model-id'" in ''.join(c['source']))
    compile(code, '<stage1-cell>', 'exec')
    assert 'sft_dataset_qwen7b_folder_schema_v1' in code
    assert '--question-only' not in code
    assert "'--max-tokens', '2048'" in code
    assert 'src/agent/prompts.py' in code and 'src/profiler/business_loader.py' in code
    assert 'if return_code:' in code
