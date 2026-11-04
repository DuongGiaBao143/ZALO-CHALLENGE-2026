"""Upload stable checkpoint snapshots from rank zero while training continues."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading


def backup_error_details(error):
    message = str(error)
    token = os.environ.get('HF_TOKEN')
    if token:
        message = message.replace(token, '[REDACTED]')
    message = re.sub(r'hf_[A-Za-z0-9_-]+', '[REDACTED]', message)
    message = re.sub(r'(?i)Bearer\s+\S+', 'Bearer [REDACTED]', message)
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    return dict(type=type(error).__name__, message=message[:1500], http_status=status)


class HubBackup:
    def __init__(self, api, repo_id, output_dir, remote_prefix):
        self.api, self.repo_id = api, repo_id
        self.output = Path(output_dir).resolve()
        self.staging = self.output.parent / f'.{self.output.name}-hub-staging'
        self.staging.mkdir(parents=True, exist_ok=True)
        self.remote_prefix = remote_prefix.strip('/')
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.futures = []
        self.snapshot_failures = 0
        self.failed_snapshot = None
        self.lock = threading.Lock()

    def _event(self, status, name, error=None):
        event = dict(time=datetime.now(timezone.utc).isoformat(), status=status, artifact=name,
                     repo_id=self.repo_id)
        if error:
            event['error'] = backup_error_details(error)
        with self.lock:
            with (self.output / 'hub_backup.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event) + '\n')
        print(f"[HF backup] {status}: {name}" +
              (f" ({event['error']['type']}: {event['error']['message']})" if error else ''), flush=True)

    def submit(self, source):
        source = Path(source).resolve()
        if not source.is_relative_to(self.output) or not source.is_dir():
            raise ValueError('Only artifact directories inside this run may be uploaded')
        if any(not future.done() for future in self.futures):
            self._event('deferred' if source.name == 'final_adapter' else 'skipped_busy', source.name)
            return
        if self.failed_snapshot is not None:
            self._remove_snapshot(self.failed_snapshot)
            self.failed_snapshot = None
        required = sum(p.stat().st_size for p in source.rglob('*') if p.is_file())
        if shutil.disk_usage(self.staging).free < required + 1024**3:
            self._event('skipped_low_disk', source.name)
            return
        # Checkpoint rotation may delete the source before an upload completes.
        snapshot = Path(tempfile.mkdtemp(prefix=source.name + '-', dir=self.staging))
        try:
            shutil.copytree(source, snapshot, dirs_exist_ok=True)
        except Exception as error:
            self.snapshot_failures += 1
            self._event('snapshot_failed', source.name, error)
            self._remove_snapshot(snapshot)
            return
        self._event('queued', source.name)
        self.futures.append(self.worker.submit(self._upload, snapshot, source.name))

    def _upload(self, snapshot, name):
        try:
            self.api.upload_folder(repo_id=self.repo_id, repo_type='model', folder_path=str(snapshot),
                                   path_in_repo=f'{self.remote_prefix}/{name}',
                                   ignore_patterns=['README.md'],
                                   commit_message=f'Backup {self.remote_prefix}/{name}')
        except Exception as error:
            self._event('upload_failed', name, error)
            # Keep the latest failed snapshot; retaining every failure can fill Kaggle's disk.
            if self.failed_snapshot is not None:
                self._remove_snapshot(self.failed_snapshot)
            self.failed_snapshot = snapshot
            return False
        self._event('uploaded', name)
        self._remove_snapshot(snapshot)
        return True

    def _remove_snapshot(self, snapshot):
        target = snapshot.resolve()
        if not target.is_relative_to(self.staging.resolve()) or target == self.staging.resolve():
            raise ValueError('Unsafe backup staging cleanup path')
        shutil.rmtree(target)

    def finish(self):
        self.worker.shutdown(wait=True)
        results = [future.result() for future in self.futures]
        failed = results.count(False) + self.snapshot_failures
        print(f'[HF backup] uploaded={results.count(True)} failed={failed}; local artifacts preserved', flush=True)
        return dict(uploaded=results.count(True), failed=failed)
