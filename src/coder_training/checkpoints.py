"""Complete, fingerprinted adapter checkpoints; base weights stay in the original Input."""
import json
from pathlib import Path
import re

from src.coder_training.io_utils import file_hash


def checkpoint_files(world_size=2, has_scaler=True):
    names = {'adapter_config.json', 'adapter_model.safetensors', 'optimizer.bin',
             'scheduler.pt', 'trainer_state.json'}
    names.update({'rng_state.pth'} if world_size == 1 else
                 {f'rng_state_{rank}.pth' for rank in range(world_size)})
    if has_scaler:
        names.add('scaler.pt')
    return names


def mark_checkpoint_complete(path, config_hash, world_size=2, has_scaler=True):
    path = Path(path)
    names = checkpoint_files(world_size, has_scaler)
    step = json.loads((path / 'trainer_state.json').read_text())['global_step']
    manifest = dict(format='adapter-fsdp1-v1', config_hash=config_hash, world_size=world_size,
                    step=step, has_scaler=has_scaler,
                    files={name: file_hash(path / name) for name in sorted(names)})
    pending = path / 'checkpoint_complete.pending.json'
    pending.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    pending.replace(path / 'checkpoint_complete.json')


def verify_checkpoint(path, config_hash, world_size=2):
    path = Path(path).resolve()
    manifest = json.loads((path / 'checkpoint_complete.json').read_text(encoding='utf-8'))
    if (manifest.get('format') != 'adapter-fsdp1-v1' or manifest.get('config_hash') != config_hash
            or manifest.get('world_size') != world_size):
        raise ValueError('Checkpoint model/data/config/version or world size mismatch')
    if set(manifest['files']) != checkpoint_files(world_size, manifest['has_scaler']):
        raise ValueError('Incomplete checkpoint file manifest')
    for name, digest in manifest['files'].items():
        if file_hash(path / name) != digest:
            raise ValueError(f'Checkpoint checksum mismatch: {name}')
    state = json.loads((path / 'trainer_state.json').read_text())
    if manifest['step'] != state['global_step'] or path.name != f"checkpoint-{manifest['step']}":
        raise ValueError('Checkpoint step mismatch')
    return path


def resolve_resume_checkpoint(value, output_dir, config_hash):
    if not value:
        return None
    if value == 'latest':
        candidates = [p for p in Path(output_dir).glob('checkpoint-*')
                      if re.fullmatch(r'checkpoint-\d+', p.name) and (p / 'checkpoint_complete.json').is_file()]
        if not candidates:
            raise FileNotFoundError('No complete checkpoint found; set RESUME_FROM_CHECKPOINT to empty for a new run')
        value = max(candidates, key=lambda p: int(p.name.split('-')[-1]))
    return verify_checkpoint(value, config_hash)
