"""Exercise the standalone script's preprocessing without PEFT or model downloads."""

import ast
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import pytest
import torch


@pytest.fixture
def preprocessing():
    source = Path(__file__).resolve().parents[1] / 'scripts/train_sft_lora.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    names = {'DataMateDataset', 'DataMateCompletionOnlyCollator', 'prepare_dataset'}
    nodes = [node for node in tree.body
             if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names]
    namespace = dict(torch=torch, json=json, logger=logging.getLogger(__name__),
                     Any=Any, Dict=Dict, List=List)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace


class ChatTokenizer:
    """Model v4/v5 defaults; only explicit return_dict=False guarantees token lists."""

    def __init__(self, default_dict=True):
        self.default_dict = default_dict

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, return_dict=None):
        assert tokenize
        ids = [1, 2] if add_generation_prompt else [1, 2] + [3] * len(messages[-1]['content']) + [0]
        as_dict = self.default_dict if return_dict is None else return_dict
        return {'input_ids': ids, 'attention_mask': [1] * len(ids)} if as_dict else ids


def write_records(tmp_path, completions):
    path = tmp_path / 'sft.jsonl'
    records = [{'messages': [{'role': 'user', 'content': 'question'},
                              {'role': 'assistant', 'content': text}]} for text in completions]
    path.write_text('\n'.join(json.dumps(record) for record in records), encoding='utf-8')
    return str(path)


@pytest.mark.parametrize('default_dict', [False, True])
def test_tokenization_collation_and_training_loss(preprocessing, tmp_path, default_dict):
    dataset = preprocessing['prepare_dataset'](
        write_records(tmp_path, ['aa', 'b']), ChatTokenizer(default_dict), max_seq_len=8
    )
    batch = preprocessing['DataMateCompletionOnlyCollator'](pad_token_id=0)(list(dataset))
    assert batch['input_ids'].dtype == torch.long
    assert batch['input_ids'].shape == (2, 8)
    assert batch['labels'][0].tolist() == [-100, -100, 3, 3, 0, -100, -100, -100]
    assert batch['attention_mask'][0].tolist() == [1, 1, 1, 1, 1, 0, 0, 0]
    assert batch['labels'][1].tolist() == [-100, -100, 3, 0, -100, -100, -100, -100]
    model = torch.nn.Sequential(torch.nn.Embedding(4, 8), torch.nn.Linear(8, 4))
    logits = model(batch['input_ids'])[:, :-1].contiguous()
    loss = torch.nn.functional.cross_entropy(logits.view(-1, 4), batch['labels'][:, 1:].reshape(-1))
    assert torch.isfinite(loss)
    loss.backward()
    assert model[1].weight.grad is not None


def test_length_filter_counts_tokens_not_dictionary_keys(preprocessing, tmp_path):
    path = write_records(tmp_path, ['short', 'much too long'])
    assert len(preprocessing['prepare_dataset'](path, ChatTokenizer(), max_seq_len=8)) == 1
    with pytest.raises(ValueError, match='No samples retained'):
        preprocessing['prepare_dataset'](path, ChatTokenizer(), max_seq_len=2)


def test_rejects_dictionary_even_if_tokenizer_ignores_return_dict(preprocessing, tmp_path):
    class BrokenTokenizer:
        def apply_chat_template(self, *args, **kwargs):
            return {'input_ids': [1, 2], 'attention_mask': [1, 1]}

    with pytest.raises(TypeError, match='integer token IDs'):
        preprocessing['prepare_dataset'](write_records(tmp_path, ['code']), BrokenTokenizer())


def test_rejects_prompt_prefix_mismatch(preprocessing, tmp_path):
    class BrokenTokenizer(ChatTokenizer):
        def apply_chat_template(self, *args, **kwargs):
            ids = super().apply_chat_template(*args, **kwargs)
            return ids if kwargs['add_generation_prompt'] else [9] + ids

    with pytest.raises(ValueError, match='prefix mismatch'):
        preprocessing['prepare_dataset'](write_records(tmp_path, ['code']), BrokenTokenizer())


def test_compact_records_are_expanded_before_tokenizing(preprocessing, tmp_path):
    split = tmp_path / 'train'
    shop = split / 'data' / 'biz_test'
    shop.mkdir(parents=True)
    (shop / 'sales.csv').write_text('amount\n10\n', encoding='utf-8')
    (split / 'questions.jsonl').write_text(json.dumps(dict(
        id='q_test', business_id='biz_test', question='Total?', as_of_date='2026-09-07')), encoding='utf-8')
    compact = tmp_path / 'compact.jsonl'
    code = 'print(1)'
    compact.write_text(json.dumps(dict(id='q_test', business_id='biz_test', code=code)), encoding='utf-8')
    samples = preprocessing['prepare_dataset'](str(compact), ChatTokenizer(), 1000, data_train_dir=str(split))
    assert len(samples) == 1
    assert samples[0]['labels'][:2] == [-100, -100]
    assert len(samples[0]['labels']) == len(f'```python\n{code}\n```') + 3
