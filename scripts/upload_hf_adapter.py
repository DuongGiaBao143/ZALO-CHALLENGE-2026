"""Preflight or retry a private adapter upload in a fresh online process (no GPU)."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

def safe_error(error):
    text = str(error)
    if os.environ.get('HF_TOKEN'):
        text = text.replace(os.environ['HF_TOKEN'], '[REDACTED]')
    text = re.sub(r'hf_[A-Za-z0-9_-]+', '[REDACTED]', text)
    return re.sub(r'(?i)Bearer\s+\S+', 'Bearer [REDACTED]', text)[:1500]


def upload(api, repo, prefix, adapter_dir=None):
    repo_id = repo if '/' in repo else api.whoami()['name'] + '/' + repo
    api.create_repo(repo_id=repo_id, repo_type='model', private=True, exist_ok=True)
    if not api.repo_info(repo_id, repo_type='model').private:
        raise ValueError('Destination repository must be private')
    result = dict(repo_id=repo_id, path_in_repo=prefix, status='write_verified')
    if adapter_dir is None:
        api.upload_file(repo_id=repo_id, repo_type='model',
                        path_or_fileobj=b'{"status":"write_verified"}\n',
                        path_in_repo=prefix + '/upload_probe.json', commit_message='Verify training backup write access')
    else:
        adapter = Path(adapter_dir).resolve()
        required = ['adapter_config.json', 'adapter_model.safetensors']
        for name in required:
            if not (adapter / name).is_file() or (adapter / name).stat().st_size == 0:
                raise FileNotFoundError(f'Missing adapter file: {adapter / name}')
        remote = prefix.rstrip('/') + '/final_adapter'
        for attempt in range(3):
            try:
                commit = api.upload_folder(repo_id=repo_id, repo_type='model', folder_path=str(adapter),
                    path_in_repo=remote, ignore_patterns=['README.md'],
                    commit_message=f'Upload verified adapter to {remote}')
                break
            except Exception as error:
                status = getattr(getattr(error, 'response', None), 'status_code', None)
                if isinstance(error, ValueError) or status in (400, 401, 403, 404) or attempt == 2:
                    raise
                print(f'Upload retry {attempt + 1}: {type(error).__name__}: {safe_error(error)}', flush=True)
                time.sleep(2 ** attempt)
        remote_files = set(api.list_repo_files(repo_id=repo_id, repo_type='model', revision=commit.oid))
        if not all(remote + '/' + name in remote_files for name in required):
            raise RuntimeError('Upload returned without both required files at the committed revision')
        result.update(status='uploaded', path_in_repo=remote, commit=commit.oid)
    result['url'] = 'https://huggingface.co/' + repo_id + '/tree/main/' + result['path_in_repo']
    return result


def main():
    # Run this script in a fresh process; Hub settings are cached on first import.
    os.environ['HF_HUB_OFFLINE'] = '0'
    os.environ['TRANSFORMERS_OFFLINE'] = '0'
    os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--adapter-dir')
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    if not os.environ.get('HF_TOKEN', '').strip():
        parser.error('HF_TOKEN must be provided through the environment/Kaggle Secrets')
    from huggingface_hub import HfApi
    try:
        result = upload(HfApi(token=os.environ['HF_TOKEN']), args.repo, args.prefix, args.adapter_dir)
    except Exception as error:
        result = dict(status='failed', error_type=type(error).__name__, error=safe_error(error),
                      http_status=getattr(getattr(error, 'response', None), 'status_code', None))
        status = 1
    else:
        status = 0
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    return status


if __name__ == '__main__':
    sys.exit(main())
