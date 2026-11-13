import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import zipfile

import nbformat
import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'notebooks/Train_DeepSeek_R1_14B_code_only_Colab.ipynb'


def cells():
    return {c.id: c.source for c in nbformat.read(NOTEBOOK, as_version=4).cells if c.cell_type == 'code'}


def setup_finish(tmp_path, monkeypatch, failure=None, bad_helper=False):
    sources = cells()
    helper = (ROOT / 'scripts/upload_hf_adapter.py').read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('scripts/upload_hf_adapter.py', b'raise RuntimeError("must not execute")' if bad_helper else helper)
    helper_zip = tmp_path / 'helper.zip'
    helper_zip.write_bytes(buffer.getvalue())
    sources['colab-hf-preflight'] = sources['colab-hf-preflight'].replace(
        'aa083947de5730bbe8671b20602f139423bb586439d94d64b9da2f2c3b9a2250',
        hashlib.sha256(helper_zip.read_bytes()).hexdigest())

    class API:
        def __init__(self):
            self.files = {}
            self.uploads = []

        def repo_info(self, *args, **kwargs):
            return SimpleNamespace(private=failure != 'public')

        def create_repo(self, **kwargs):
            assert kwargs['private'] is True

        def upload_file(self, *, path_in_repo, path_or_fileobj, **kwargs):
            if failure == 'archive-upload' and path_in_repo.endswith('.zip'):
                raise RuntimeError('simulated archive upload failed')
            data = path_or_fileobj if isinstance(path_or_fileobj, bytes) else Path(path_or_fileobj).read_bytes()
            self.files[path_in_repo] = data
            self.uploads.append(path_in_repo)
            return SimpleNamespace(oid='a' * 40)

        def upload_folder(self, *, folder_path, path_in_repo, **kwargs):
            for p in Path(folder_path).iterdir():
                self.files[path_in_repo + '/' + p.name] = p.read_bytes()
            self.uploads.append(path_in_repo)
            return SimpleNamespace(oid='b' * 40)

        def list_repo_files(self, **kwargs):
            return list(self.files)

        def get_paths_info(self, repo, *, paths, revision, **kwargs):
            path = paths[0]
            data = self.files[path]
            digest = hashlib.sha256(data).hexdigest()
            if (failure == 'adapter-hash' and path.endswith('.safetensors')) or (
                    failure == 'archive-hash' and path.endswith('.zip')):
                digest = '0' * 64
            return [SimpleNamespace(size=len(data), lfs=None if path.endswith('.json') else SimpleNamespace(sha256=digest))]

    api = API()
    downloads = []

    def download(**kwargs):
        downloads.append(kwargs)
        assert kwargs['token'] == 'fixture-secret'
        if kwargs['repo_type'] == 'dataset':
            assert kwargs['revision'] == '5db72bef94543ef7619f8dc0878fe8578b68a954'
            return str(helper_zip)
        path = tmp_path / 'download' / kwargs['filename']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(api.files[kwargs['filename']])
        return str(path)

    shutdowns = []
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(HfApi=lambda **kw: api))
    monkeypatch.setitem(sys.modules, 'google.colab', SimpleNamespace(runtime=SimpleNamespace(unassign=lambda: shutdowns.append(True))))
    monkeypatch.setattr(sys, 'path', sys.path.copy())
    run = tmp_path / 'run'
    adapter = run / 'train/final_adapter'
    adapter.mkdir(parents=True)
    (adapter / 'adapter_config.json').write_text('{}')
    (adapter / 'adapter_model.safetensors').write_bytes(b'fixture adapter')
    for name in ('smoke/final_adapter/adapter_model.safetensors', 'train/checkpoints/optimizer.pt',
                 'train/checkpoints/train_results.json', 'train/checkpoints/trainer_state.json', 'train.log'):
        path = run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')
    work = tmp_path / 'work'
    work.mkdir()
    ns = dict(Path=Path, hashlib=hashlib, json=json, zipfile=zipfile, sys=sys, HF_TOKEN='fixture-secret',
              HF_REPO='owner/private-adapter', BUNDLE_REPO='owner/private-handoff', REMOTE_PREFIX='runs/test',
              RUN_NAME='test', WORK=work, RUN_ROOT=run, INPUT=tmp_path / 'input', ADAPTER=adapter,
              hf_hub_download=download, AUTO_DISCONNECT=True,
              manifest=dict(model_repo='base/model', model_revision='c' * 40))
    return sources, ns, api, downloads, shutdowns


@pytest.mark.parametrize('failure', [None, 'public', 'adapter-hash', 'archive-upload', 'archive-hash'])
def test_colab_only_disconnects_after_both_verified_uploads(tmp_path, monkeypatch, failure):
    sources, ns, api, downloads, shutdowns = setup_finish(tmp_path, monkeypatch, failure)

    def finish():
        for name in ('colab-hf-preflight', 'colab-hf-adapter', 'colab-hf-archive', 'colab-auto-disconnect'):
            exec(sources[name], ns)

    if failure:
        with pytest.raises((ValueError, RuntimeError)):
            finish()
        with pytest.raises((FileNotFoundError, RuntimeError)):
            exec(sources['colab-auto-disconnect'], ns)
        assert not shutdowns
    else:
        finish()
        assert shutdowns == [True]
        receipt = json.loads((ns['RUN_ROOT'] / 'hf_archive.json').read_text())
        assert receipt['verified'] and receipt['status'] == 'uploaded'
        with zipfile.ZipFile(io.BytesIO(api.files[receipt['path_in_repo']])) as archive:
            assert 'train/final_adapter/adapter_model.safetensors' in archive.namelist()
            assert 'train/train_results.json' in archive.namelist()
            assert not any('optimizer' in p or p.startswith('smoke/final_adapter/') for p in archive.namelist())
        config = json.loads((ns['ADAPTER'] / 'adapter_config.json').read_text())
        assert config['base_model_name_or_path'] == 'base/model' and config['revision'] == 'c' * 40
        assert any(d['repo_type'] == 'model' and d['revision'] == 'b' * 40 for d in downloads)


def test_bad_helper_hash_stops_before_execution_or_upload(tmp_path, monkeypatch):
    sources, ns, api, _, shutdowns = setup_finish(tmp_path, monkeypatch, bad_helper=True)
    with pytest.raises(ValueError, match='source hash mismatch'):
        exec(sources['colab-hf-preflight'], ns)
    assert not api.uploads and not shutdowns


@pytest.mark.parametrize('enabled,wrong_run', [(False, False), (True, True)])
def test_disconnect_respects_option_and_rejects_receipts_from_another_run(tmp_path, monkeypatch, enabled, wrong_run):
    sources = cells()
    shutdowns = []
    monkeypatch.setitem(sys.modules, 'google.colab', SimpleNamespace(runtime=SimpleNamespace(unassign=lambda: shutdowns.append(True))))
    for name in ('hf_upload.json', 'hf_archive.json'):
        (tmp_path / name).write_text(json.dumps(dict(verified=True, status='uploaded',
            run_name='old' if wrong_run else 'test', repo_id='owner/private')))
    ns = dict(json=json, RUN_ROOT=tmp_path, RUN_NAME='test', HF_REPO='owner/private', AUTO_DISCONNECT=enabled)
    if wrong_run:
        with pytest.raises(RuntimeError, match='giữ runtime'):
            exec(sources['colab-auto-disconnect'], ns)
    else:
        exec(sources['colab-auto-disconnect'], ns)
    assert not shutdowns
