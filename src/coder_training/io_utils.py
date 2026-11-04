"""Read-only input boundaries and content fingerprints shared by training tools."""
import hashlib
import json
from pathlib import Path


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    files = {p.relative_to(root).as_posix(): file_hash(p)
             for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def writable_output(path, *input_roots):
    path = Path(path).resolve()
    roots = [Path('/kaggle/input').resolve(), Path(__file__).resolve().parents[2] / 'data']
    roots.extend(Path(p).resolve() for p in input_roots)
    for root in roots:
        if path == root or root in path.parents:
            raise ValueError(f'Output must be outside read-only input: {path}')
    return path


def read_unique_jsonl(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    ids = [str(row['id']) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f'Duplicate question/answer IDs in {path}')
    return rows


def select_questions(questions, limit, seed=42):
    """Round-robin businesses so a short pilot does not consist of the first shop only."""
    import random
    rng = random.Random(seed)
    groups = {}
    for question in questions:
        groups.setdefault(question.business_id, []).append(question)
    businesses = sorted(groups)
    rng.shuffle(businesses)
    for group in groups.values():
        rng.shuffle(group)
    ordered = []
    while any(groups.values()):
        for business in businesses:
            if groups[business]:
                ordered.append(groups[business].pop())
    if limit is not None and limit <= 0:
        raise ValueError('Question limit must be positive or None')
    return ordered if limit is None else ordered[:limit]
