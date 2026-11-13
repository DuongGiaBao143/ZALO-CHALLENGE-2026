"""Exercise notebook warm-start wiring without loading a model or GPU."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'notebooks/Train_Qwen_kaggle.ipynb'


class AdapterContinueTest(unittest.TestCase):
    def setUp(self):
        notebook = json.loads(NOTEBOOK.read_text(encoding='utf-8'))
        self.cells = [''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code']
        source = next(c for c in self.cells if 'BASE_ARGS = ' in c)
        self.setup_code = source[source.index('BASE_ARGS = '):].split('run_logged(', 1)[0]
        (ROOT / 'tmp').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(temporary.cleanup)
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(temporary.name)
        Path('scripts').mkdir()
        Path('scripts/train_sft_kaggle_2t4.py').write_text('# --init-adapter', encoding='utf-8')
        self.adapter = Path('adapter').resolve()
        self.adapter.mkdir()
        self.config = dict(peft_type='LORA', r=16, lora_alpha=32,
                           target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj',
                                           'gate_proj', 'up_proj', 'down_proj'])
        (self.adapter / 'adapter_config.json').write_text(json.dumps(self.config))
        (self.adapter / 'adapter_model.safetensors').write_bytes(b'test fixture; never loaded')
        self.env = dict(Path=Path, json=json, MODEL_DIR='base', DATASET='dataset', MAX_SEQ_LEN=8192,
                        EPOCHS=1, LEARNING_RATE=1e-4, GRAD_ACCUM=4, INIT_ADAPTER_DIR=str(self.adapter),
                        HF_ADAPTER_PATH='', HF_INPUT_REPO='Crinkk/Zalo-challenge', WORK=Path.cwd(),
                        RESUME_FROM_CHECKPOINT='', EVAL_ADAPTER_DIR='')

    def test_hf_adapter_reaches_smoke_and_full_train(self):
        model_info = Mock(return_value=SimpleNamespace(sha='pinned-commit'))
        download = Mock(side_effect=lambda *, filename, **kwargs: self.adapter / filename)
        self.env.update(INIT_ADAPTER_DIR='', get_hf_token=lambda: 'fixture-token',
                        HfApi=Mock(return_value=SimpleNamespace(model_info=model_info)),
                        hf_hub_download=download,
                        HF_ADAPTER_PATH='https://huggingface.co/owner/model/tree/release%2Fv1/runs/final_adapter')
        exec(self.setup_code, self.env)
        model_info.assert_called_once_with('owner/model', revision='release/v1')
        self.assertEqual(download.call_args_list, [
            call(repo_id='owner/model', revision='pinned-commit', subfolder='runs/final_adapter',
                 filename=name, token='fixture-token', cache_dir=Path.cwd() / 'hf_adapters')
            for name in ('adapter_config.json', 'adapter_model.safetensors')
        ])
        commands = []
        run_root = Path('runs/new')

        def run_logged(command, log_path):
            commands.append(command)
            output = Path(command[command.index('--output-dir') + 1])
            output.mkdir(parents=True, exist_ok=True)
            report = dict(status='passed', checkpoint_restore_checked=True,
                          ranks=[dict(rank=i, steps=2, loss=0.5, peak_vram_gib=1) for i in range(2)])
            (output / 'completed.json').write_text(json.dumps(report))

        import math
        import sys
        self.env.update(run_logged=run_logged, RUN_ROOT=run_root, math=math, sys=sys)
        exec(next(c for c in self.cells if 'LAUNCH = ' in c), self.env)
        exec(next(c for c in self.cells if "command = [*LAUNCH, *BASE_ARGS" in c), self.env)
        self.assertEqual(len(commands), 2)
        for command in commands:
            self.assertEqual(command[command.index('--init-adapter') + 1], str(self.adapter))
            self.assertEqual(command[command.index('--epochs') + 1], '1')
            self.assertNotIn('--resume', command)
        self.assertEqual((self.adapter / 'adapter_model.safetensors').read_bytes(),
                         b'test fixture; never loaded')

    def test_empty_adapter_keeps_fresh_and_resume_modes(self):
        self.env.update(INIT_ADAPTER_DIR='', RESUME_FROM_CHECKPOINT='checkpoint-10')
        exec(self.setup_code, self.env)
        self.assertNotIn('--init-adapter', self.env['BASE_ARGS'])

    def test_hf_adapter_accepts_repo_root_and_relative_folder(self):
        for selection, repo, folder in [
            ('https://huggingface.co/owner/model', 'owner/model', None),
            ('runs/test/final_adapter', 'Crinkk/Zalo-challenge', 'runs/test/final_adapter'),
        ]:
            with self.subTest(selection=selection):
                model_info = Mock(return_value=SimpleNamespace(sha='pinned-commit'))
                download = Mock(side_effect=lambda *, filename, **kwargs: self.adapter / filename)
                env = dict(self.env, INIT_ADAPTER_DIR='', HF_ADAPTER_PATH=selection,
                           get_hf_token=lambda: 'fixture-token', hf_hub_download=download,
                           HfApi=Mock(return_value=SimpleNamespace(model_info=model_info)))
                exec(self.setup_code, env)
                model_info.assert_called_once_with(repo, revision='main')
                self.assertEqual(download.call_args.kwargs['subfolder'], folder)
                self.assertEqual(env['BASE_ARGS'][-2:], ['--init-adapter', str(self.adapter)])

    def test_conflicting_modes_are_rejected(self):
        for key in ['RESUME_FROM_CHECKPOINT', 'EVAL_ADAPTER_DIR']:
            with self.subTest(key=key), self.assertRaises(ValueError):
                exec(self.setup_code, dict(self.env, **{key: 'old-run'}))
        for key in ['INIT_ADAPTER_DIR', 'RESUME_FROM_CHECKPOINT', 'EVAL_ADAPTER_DIR']:
            with self.subTest(hf_conflict=key), self.assertRaises(ValueError):
                env = dict(self.env, INIT_ADAPTER_DIR='', HF_ADAPTER_PATH='runs/final_adapter')
                exec(self.setup_code, dict(env, **{key: 'old-run'}))

    def test_missing_weights_are_rejected(self):
        (self.adapter / 'adapter_model.safetensors').unlink()
        with self.assertRaises(FileNotFoundError):
            exec(self.setup_code, self.env)

    def test_incompatible_adapter_is_rejected(self):
        for change in [dict(r=8), dict(lora_alpha=16), dict(target_modules=['q_proj']),
                       dict(use_rslora=True), dict(use_dora=True), dict(bias='all')]:
            with self.subTest(change=change):
                (self.adapter / 'adapter_config.json').write_text(json.dumps(dict(self.config, **change)))
                with self.assertRaises(ValueError):
                    exec(self.setup_code, self.env)

    def test_repaired_adapter_is_preferred(self):
        repaired = self.adapter / 'repaired'
        repaired.mkdir()
        for name in ['adapter_config.json', 'adapter_model.safetensors']:
            (repaired / name).write_bytes((self.adapter / name).read_bytes())
        exec(self.setup_code, self.env)
        self.assertEqual(self.env['BASE_ARGS'][-2:], ['--init-adapter', str(repaired)])

    def test_old_bundle_fails_before_training(self):
        Path('scripts/train_sft_kaggle_2t4.py').write_text('# old source')
        with self.assertRaises(RuntimeError):
            exec(self.setup_code, self.env)
