import json
from pathlib import Path
from types import SimpleNamespace
import threading
import sys

import pytest

from src.coder_training.hub_backup import HubBackup


def test_upload_uses_snapshot_even_if_checkpoint_rotates(tmp_path):
    output = tmp_path / 'train'
    source = output / 'checkpoint-10'
    source.mkdir(parents=True)
    (source / 'adapter.bin').write_bytes(b'original')
    started, release = threading.Event(), threading.Event()
    uploads = []

    def upload(**kwargs):
        started.set()
        assert release.wait(10)
        uploads.append((kwargs, (Path(kwargs['folder_path']) / 'adapter.bin').read_bytes()))

    backup = HubBackup(SimpleNamespace(upload_folder=upload), 'owner/private', output, 'runs/test/train')
    try:
        backup.submit(source)
        assert started.wait(5)
        (source / 'adapter.bin').write_bytes(b'rotated')
    finally:
        release.set()
        report = backup.finish()
    assert report == dict(uploaded=1, failed=0)
    assert uploads[0][1] == b'original'
    assert uploads[0][0]['path_in_repo'] == 'runs/test/train/checkpoint-10'
    assert uploads[0][0]['ignore_patterns'] == ['README.md']
    assert not list(backup.staging.iterdir())
    assert (source / 'adapter.bin').read_bytes() == b'rotated'


def test_upload_failure_keeps_local_snapshot_and_never_logs_token(tmp_path, capsys):
    output = tmp_path / 'train'
    source = output / 'final_adapter'
    source.mkdir(parents=True)
    (source / 'weights').write_bytes(b'local')

    def fail(**kwargs):
        raise RuntimeError('hf_do_not_print_this_token')

    backup = HubBackup(SimpleNamespace(upload_folder=fail), 'owner/private', output, 'runs/test/train')
    backup.submit(source)
    assert backup.finish() == dict(uploaded=0, failed=1)
    assert next(backup.staging.glob('*/weights')).read_bytes() == b'local'
    assert 'hf_do_not_print_this_token' not in capsys.readouterr().out
    assert 'hf_do_not_print_this_token' not in (output / 'hub_backup.jsonl').read_text()
    assert (source / 'weights').read_bytes() == b'local'


def test_backup_rejects_directory_outside_run(tmp_path):
    output = tmp_path / 'train'
    output.mkdir()
    backup = HubBackup(None, 'owner/private', output, 'runs/test/train')
    try:
        with pytest.raises(ValueError, match='inside this run'):
            backup.submit(tmp_path)
    finally:
        backup.finish()


def test_repeated_upload_failures_keep_only_latest_snapshot(tmp_path):
    output = tmp_path / 'train'
    def fail(**kwargs):
        raise ValueError('upload failed')
    backup = HubBackup(SimpleNamespace(upload_folder=fail), 'owner/private', output, 'runs/test/train')
    for step in range(3):
        source = output / f'checkpoint-{step}'
        source.mkdir(parents=True)
        (source / 'weights').write_bytes(bytes([step]))
        backup.submit(source)
        backup.futures[-1].result(timeout=10)
    assert backup.finish() == dict(uploaded=0, failed=3)
    snapshots = list(backup.staging.iterdir())
    assert len(snapshots) == 1 and (snapshots[0] / 'weights').read_bytes() == b'\x02'
    assert len(list(output.glob('checkpoint-*'))) == 3


def test_slow_upload_does_not_accumulate_checkpoint_snapshots(tmp_path):
    output = tmp_path / 'train'
    source = output / 'checkpoint-10'
    source.mkdir(parents=True)
    (source / 'weights').write_bytes(b'checkpoint')
    started, release = threading.Event(), threading.Event()

    def upload(**kwargs):
        started.set()
        assert release.wait(10)

    backup = HubBackup(SimpleNamespace(upload_folder=upload), 'owner/private', output, 'runs/test/train')
    try:
        backup.submit(source)
        assert started.wait(5)
        another = output / 'checkpoint-20'
        another.mkdir()
        (another / 'weights').write_bytes(b'next')
        backup.submit(another)
        final = output / 'final_adapter'
        final.mkdir()
        (final / 'weights').write_bytes(b'final')
        backup.submit(final)
        assert len(backup.futures) == len(list(backup.staging.iterdir())) == 1
    finally:
        release.set()
        backup.finish()
    events = [json.loads(line) for line in (output / 'hub_backup.jsonl').read_text().splitlines()]
    assert {'skipped_busy', 'deferred'} <= {event['status'] for event in events}
    assert (final / 'weights').read_bytes() == b'final'


def test_low_disk_skips_snapshot_without_touching_artifact(tmp_path, monkeypatch):
    output = tmp_path / 'train'
    source = output / 'final_adapter'
    source.mkdir(parents=True)
    (source / 'weights').write_bytes(b'original')
    monkeypatch.setattr('src.coder_training.hub_backup.shutil.disk_usage', lambda p: SimpleNamespace(free=1))
    backup = HubBackup(None, 'owner/private', output, 'runs/test/train')
    backup.submit(source)
    assert not list(backup.staging.iterdir())
    assert backup.finish() == dict(uploaded=0, failed=0)
    assert (source / 'weights').read_bytes() == b'original'
    assert json.loads((output / 'hub_backup.jsonl').read_text())['status'] == 'skipped_low_disk'


def test_failed_snapshot_copy_removes_partial_copy_only(tmp_path, monkeypatch):
    output = tmp_path / 'train'
    source = output / 'final_adapter'
    source.mkdir(parents=True)
    (source / 'weights').write_bytes(b'original')

    def fail(source, target, **kwargs):
        (target / 'partial.bin').write_bytes(b'partial')
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr('src.coder_training.hub_backup.shutil.copytree', fail)
    backup = HubBackup(None, 'owner/private', output, 'runs/test/train')
    backup.submit(source)
    assert backup.finish() == dict(uploaded=0, failed=1)
    assert not list(backup.staging.iterdir())
    assert (source / 'weights').read_bytes() == b'original'


def test_error_details_keep_reason_and_http_status_but_redact_tokens(tmp_path, monkeypatch):
    from src.coder_training.hub_backup import backup_error_details
    monkeypatch.setenv('HF_TOKEN', 'private-secret-without-standard-prefix')
    error = ValueError('Invalid configuration: private-secret-without-standard-prefix hf_example_token Bearer another-token')
    error.response = SimpleNamespace(status_code=403)
    details = backup_error_details(error)
    assert details['http_status'] == 403 and 'Invalid configuration' in details['message']
    assert 'private-secret' not in details['message'] and 'hf_example' not in details['message']
    assert 'another-token' not in details['message']


@pytest.mark.parametrize('private', [True, False])
def test_notebook_creates_private_repo_and_checks_existing_visibility(tmp_path, monkeypatch, private):
    notebook = json.loads((Path(__file__).resolve().parents[1] /
        'notebooks/02_train_sft_qwen7b_kaggle_2t4_208.ipynb').read_text(encoding='utf-8'))
    cell = next(''.join(c['source']) for c in notebook['cells']
                if c['cell_type']=='code' and 'api.create_repo(' in ''.join(c['source']))
    calls = []
    api = SimpleNamespace(whoami=lambda: {'name':'owner'},
        create_repo=lambda **kwargs:calls.append(kwargs), repo_info=lambda *a,**kw:SimpleNamespace(private=private))
    monkeypatch.setenv('HF_TOKEN', 'test-token-never-written-to-notebook')
    monkeypatch.setenv('DATAMATE_HF_REPO', '')
    monkeypatch.setenv('DATAMATE_HF_PREFIX', '')
    monkeypatch.setenv('HF_HUB_OFFLINE', '0')
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(HfApi=lambda **kwargs:api))
    namespace = dict(HF_REPO_NAME='Zalo-challenge', RUN_NAME='test', os=__import__('os'))
    if private:
        exec(compile(cell, '<hf-cell>', 'exec'), namespace)
        assert namespace['os'].environ['DATAMATE_HF_REPO'] == 'owner/Zalo-challenge'
    else:
        with pytest.raises(AssertionError, match='private'):
            exec(compile(cell, '<hf-cell>', 'exec'), namespace)
    assert calls == [dict(repo_id='owner/Zalo-challenge', repo_type='model', private=True, exist_ok=True)]
