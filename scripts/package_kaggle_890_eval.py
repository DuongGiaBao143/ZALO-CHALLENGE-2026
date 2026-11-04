"""Package training code and the existing 30-question train pilot for Kaggle."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / 'result/kaggle_qwen7b_890_portable_train_eval_bundle'
assert not OUTPUT.exists(), 'Choose a fresh bundle path; do not overwrite an existing package'


def copy(source, relative):
    target = OUTPUT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


questions = [json.loads(line) for line in (ROOT / 'result/baseline_7b_pilot/pilot_questions_30.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
golds = [json.loads(line) for line in (ROOT / 'eval_gold/pilot_gold_30.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
official_questions = {row['id']: row for line in (ROOT / 'data/train/questions.jsonl').read_text(encoding='utf-8').splitlines() if line.strip() for row in [json.loads(line)]}
official_golds = {row['id']: row for line in (ROOT / 'data/train/answers.jsonl').read_text(encoding='utf-8').splitlines() if line.strip() for row in [json.loads(line)]}
assert len(questions) == len(golds) == len({q['id'] for q in questions}) == 30
assert {q['id'] for q in questions} == {g['id'] for g in golds}
for q in questions:
    assert all(q[key] == official_questions[q['id']][key] for key in q)
for gold in golds:
    assert gold['answer'] == official_golds[gold['id']]['answer']
    assert gold['type'] == official_golds[gold['id']]['type']

for relative in ['requirements-kaggle-sft.txt', 'configs/accelerate_kaggle_2t4_sft.yaml',
                 'scripts/train_sft_kaggle_2t4.py', 'scripts/train_sft_lora.py',
                 'scripts/build_sft_dataset.py',
                 'scripts/upload_hf_adapter.py',
                 'docs/KAGGLE_QWEN7B_890_PORTABLE.md', 'notebooks/upload_trained_qwen7b_to_hf.ipynb',
                 'scripts/evaluate_pilot_30.py', 'notebooks/02_train_sft_qwen7b_kaggle_2t4_890.ipynb']:
    copy(ROOT / relative, relative)
for source in (ROOT / 'src').rglob('*.py'):
    copy(source, source.relative_to(ROOT))
compact = [json.loads(line) for line in (ROOT / 'verified_sft_dataset.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
assert len(compact) == 890 and len({row['id'] for row in compact}) == 890
assert all(set(row) == {'id', 'business_id', 'code'} for row in compact)
copy(ROOT / 'verified_sft_dataset.jsonl', 'dataset/verified_sft_dataset.jsonl')
train_context = OUTPUT / 'training/train'
train_context.mkdir(parents=True)
with (train_context / 'questions.jsonl').open('w', encoding='utf-8') as stream:
    for row in compact:
        question = official_questions[row['id']]
        assert question['business_id'] == row['business_id']
        stream.write(json.dumps(question, ensure_ascii=False) + '\n')
for name in ['rulebook.md', 'calendar.csv']:
    copy(ROOT / 'data/train' / name, f'training/train/{name}')
for business_id in sorted({row['business_id'] for row in compact}):
    source_dir = ROOT / 'data/train/data' / business_id
    for source in source_dir.rglob('*'):
        if source.is_file():
            copy(source, Path('training/train/data') / business_id / source.relative_to(source_dir))
notebook_path = OUTPUT / 'notebooks/02_train_sft_qwen7b_kaggle_2t4_890.ipynb'
notebook = json.loads(notebook_path.read_text(encoding='utf-8'))
dataset_hash = hashlib.sha256((OUTPUT / 'dataset/verified_sft_dataset.jsonl').read_bytes()).hexdigest()
for cell in notebook['cells']:
    source = ''.join(cell.get('source', []))
    source = re.sub(r"EXPECTED_DATA_SHA256 = '[0-9a-f]+'", f"EXPECTED_DATA_SHA256 = '{dataset_hash}'", source)
    source = source.replace('vllm-eval-v1', 'portable-sft-hf-v3').replace('portable-sft-v2', 'portable-sft-hf-v3').replace(
        'datamate_qwen7b_890_train_eval_kaggle_input.zip', 'datamate_qwen7b_890_portable_train_eval_kaggle_input.zip')
    cell['source'] = source.splitlines(keepends=True)
notebook_path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
copy(ROOT / 'result/baseline_7b_pilot/pilot_questions_30.jsonl', 'evaluation/pilot_questions_30.jsonl')
copy(ROOT / 'eval_gold/pilot_gold_30.jsonl', 'evaluation/pilot_gold_30.jsonl')
for name in ['rulebook.md', 'calendar.csv']:
    copy(ROOT / 'data/train' / name, f'evaluation/train/{name}')
for business_id in sorted({q['business_id'] for q in questions}):
    source_dir = ROOT / 'data/train/data' / business_id
    assert source_dir.is_dir(), source_dir
    for source in source_dir.rglob('*'):
        if source.is_file():
            copy(source, Path('evaluation/train/data') / business_id / source.relative_to(source_dir))
files = {p.relative_to(OUTPUT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(OUTPUT.rglob('*')) if p.is_file()}
training_ids = {row['id'] for row in compact}
assert len(training_ids) == 890
manifest = dict(bundle='datamate-qwen7b-sft890-2t4', revision='portable-sft-hf-v3', rows=890,
                dataset_sha256=files['dataset/verified_sft_dataset.jsonl'], files=files,
                pilot_questions=30, pilot_training_id_overlap=len(training_ids & {q['id'] for q in questions}))
(OUTPUT / 'bundle_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
archive = ROOT / 'result/datamate_qwen7b_890_portable_train_eval_kaggle_input.zip'
assert not archive.exists()
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
    for source in sorted(OUTPUT.rglob('*')):
        if source.is_file():
            bundle.write(source, source.relative_to(OUTPUT))
with zipfile.ZipFile(archive) as bundle:
    assert bundle.testzip() is None
print(json.dumps(dict(zip=str(archive), bytes=archive.stat().st_size, files=len(files),
                      pilot_training_id_overlap=manifest['pilot_training_id_overlap']), indent=2))
