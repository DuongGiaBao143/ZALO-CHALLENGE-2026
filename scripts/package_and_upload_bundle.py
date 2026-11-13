#!/usr/bin/env python3
"""Build and upload the complete self-contained Kaggle bundle to Hugging Face.

Includes:
- src/ (with full rulebook support in system prompt & solver)
- scripts/ (train and evaluate scripts)
- configs/
- data/train/ (raw training data, calendar.csv, rulebook.md)
- result/deepseek_r1_1109_sft_train_ready.jsonl (0% thinking, 100% pure code)
- dev/questions.jsonl & dev/gold.jsonl (unseen 30 questions + gold)
"""

import json
import os
import shutil
import sys
import zipfile
from pathlib import Path
from huggingface_hub import HfApi, get_token, hf_hub_download

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 0a. Patch scripts/train_sft_kaggle_2t4_reasoning.py for safe FSDP1 + init_adapter
tr_script = ROOT / "scripts" / "train_sft_kaggle_2t4_reasoning.py"
if tr_script.exists():
    t_txt = tr_script.read_text(encoding="utf-8").replace("\r\n", "\n")
    old_peft = """    if args.init_adapter:
        # Continue fine-tuning from an existing LoRA adapter (r/alpha/targets come from its adapter_config.json)
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.init_adapter, is_trainable=True)
    else:
        model = get_peft_model(model, LoraConfig(
            task_type=TaskType.CAUSAL_LM, r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.0, bias='none',
            target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']))"""
    new_peft = """    model = get_peft_model(model, LoraConfig(
        task_type=TaskType.CAUSAL_LM, r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.0, bias='none',
        target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']))
    if args.init_adapter:
        from safetensors.torch import load_file
        from peft import set_peft_model_state_dict
        adapter_dir = Path(args.init_adapter)
        if (adapter_dir / 'repaired' / 'adapter_model.safetensors').is_file():
            adapter_dir = adapter_dir / 'repaired'
        init_state = load_file(str(adapter_dir / 'adapter_model.safetensors'), device='cpu')
        init_state = {k.replace('_checkpoint_wrapped_module.', ''): v for k, v in init_state.items()}
        result = set_peft_model_state_dict(model, init_state)
        unexpected = getattr(result, 'unexpected_keys', [])
        if unexpected:
            raise ValueError(f'--init-adapter has {len(unexpected)} unexpected keys, e.g. {unexpected[:3]}')
        if main:
            print(f'Warm-started LoRA from {adapter_dir} ({len(init_state)} tensors)', flush=True)"""
    if old_peft in t_txt:
        t_txt = t_txt.replace(old_peft, new_peft, 1)
    old_upd = """        def _fsdp_qlora_plugin_updates(self):
            super()._fsdp_qlora_plugin_updates()"""
    new_upd = """        def _fsdp_qlora_plugin_updates(self):
            if hasattr(super(), '_fsdp_qlora_plugin_updates'):
                super()._fsdp_qlora_plugin_updates()"""
    if old_upd in t_txt:
        t_txt = t_txt.replace(old_upd, new_upd, 1)
    tr_script.write_text(t_txt, encoding="utf-8")
    print("✅ Updated scripts/train_sft_kaggle_2t4_reasoning.py")

# 0b. Ensure Train notebook Cell 2, Cell 4, and Cell 5 install the exact verified FSDP1 stack (transformers==4.57.1)
train_nb_path = ROOT / "notebooks" / "Train_Qwen25_14B_1M_Reasoning_Kaggle_2T4.ipynb"
if train_nb_path.exists():
    tnb = json.loads(train_nb_path.read_text(encoding="utf-8"))
    train_cell2_lines = [
        "# ==============================================================================\n",
        "# CELL 2: CÀI ĐẶT STACK CHUẨN ĐÃ KIỂM CHỨNG CHO FSDP1 + QLoRA TRÊN 2x T4\n",
        "# ==============================================================================\n",
        "import subprocess\n",
        "import sys\n",
        "\n",
        "# Ghim chính xác phiên bản transformers==4.57.1, peft==0.17.1, accelerate==1.11.0\n",
        "# (Tránh lỗi Transformers 5.x gỡ bỏ warmup_ratio, _fsdp_qlora_plugin_updates và FSDP1)\n",
        "subprocess.run([\n",
        "    sys.executable, '-m', 'pip', 'install', '--no-cache-dir', '-q',\n",
        "    'transformers==4.57.1',\n",
        "    'peft==0.17.1',\n",
        "    'accelerate==1.11.0',\n",
        "    'huggingface-hub==0.36.2',\n",
        "    'tokenizers==0.22.2',\n",
        "    'bitsandbytes==0.48.1',\n",
        "    'safetensors>=0.4.5',\n",
        "    'pyyaml>=6',\n",
        "    'psutil>=5.9',\n",
        "    'openpyxl',\n",
        "    'xlrd',\n",
        "], check=True)\n",
        "subprocess.run([sys.executable, '-m', 'pip', 'uninstall', '-y', 'torchao'], check=False)\n",
        "print('✅ Đã cài đặt xong stack FSDP1 + QLoRA chuẩn (transformers==4.57.1, peft==0.17.1, accelerate==1.11.0)!')\n",
    ]
    train_cell4_lines = [
        "# ==============================================================================\n",
        "# CELL 4: SMOKE TEST (2 STEPS) KIỂM TRA VRAM & FSDP TRÊN 2x T4 (MAX_SEQ_LEN=2560)\n",
        "# ==============================================================================\n",
        "import os\n",
        "import shutil\n",
        "import subprocess\n",
        "import sys\n",
        "\n",
        "# Cố định MAX_SEQ_LEN = 2560 (đỉnh activation ~11.2 GiB / 14.56 GiB VRAM mỗi GPU T4 khi backward 48 layers + unshard lm_head)\n",
        "MAX_SEQ_LEN = 2560\n",
        "DATA_DIR = REPO_DIR / 'data' / 'train'\n",
        "\n",
        "# 1. Tự động đảm bảo môi trường Python cho subprocess có đúng transformers==4.57.1 + accelerate==1.11.0\n",
        "ver_check = subprocess.run(\n",
        "    [sys.executable, '-c', 'import transformers, peft, accelerate; assert transformers.__version__ == \"4.57.1\"'],\n",
        "    capture_output=True, text=True\n",
        ")\n",
        "if ver_check.returncode != 0:\n",
        "    print('🔧 Phát hiện môi trường chưa ghim transformers==4.57.1. Đang đồng bộ nhanh...')\n",
        "    subprocess.run([\n",
        "        sys.executable, '-m', 'pip', 'install', '--no-cache-dir', '-q',\n",
        "        'transformers==4.57.1', 'peft==0.17.1', 'accelerate==1.11.0',\n",
        "        'huggingface-hub==0.36.2', 'tokenizers==0.22.2', 'bitsandbytes==0.48.1',\n",
        "        'safetensors>=0.4.5', 'pyyaml>=6', 'psutil>=5.9', 'openpyxl', 'xlrd',\n",
        "    ], check=True)\n",
        "    subprocess.run([sys.executable, '-m', 'pip', 'uninstall', '-y', 'torchao'], check=False)\n",
        "    print('✅ Đã cài đặt transformers==4.57.1 thành công cho tiến trình huấn luyện!')\n",
        "\n",
        "# 2. Tự động vá scripts/train_sft_lora.py trên đĩa: giữ trọn 100% Code + Schema + Question + đầu/cuối Rulebook trong 2560 tokens\n",
        "lora_script = REPO_DIR / 'scripts' / 'train_sft_lora.py'\n",
        "if lora_script.is_file():\n",
        "    l_code = lora_script.read_text(encoding='utf-8').replace('\\r\\n', '\\n')\n",
        "    old_trunc = (\n",
        "        \"        if full_len > max_seq_len:\\n\"\n",
        "        \"            if completion_format == 'r1-code-only':\\n\"\n",
        "        \"                raise ValueError(f\\\"SFT record {item.get('id', idx)} has {full_len} tokens, exceeding max_seq_len={max_seq_len}; nothing truncated\\\")\\n\"\n",
        "        \"            skipped_too_long += 1\\n\"\n",
        "        \"            continue\"\n",
        "    )\n",
        "    new_trunc = (\n",
        "        \"        if full_len > max_seq_len:\\n\"\n",
        "        \"            if completion_format == 'r1-code-only':\\n\"\n",
        "        \"                raise ValueError(f\\\"SFT record {item.get('id', idx)} has {full_len} tokens, exceeding max_seq_len={max_seq_len}; nothing truncated\\\")\\n\"\n",
        "        \"            comp_ids = full_ids[prompt_len:]\\n\"\n",
        "        \"            prompt_budget = max_seq_len - len(comp_ids)\\n\"\n",
        "        \"            if prompt_budget >= 512:\\n\"\n",
        "        \"                head_len = min(512, prompt_budget // 3)\\n\"\n",
        "        \"                tail_len = prompt_budget - head_len\\n\"\n",
        "        \"                prompt_ids = prompt_ids[:head_len] + prompt_ids[-tail_len:]\\n\"\n",
        "        \"                full_ids = prompt_ids + comp_ids\\n\"\n",
        "        \"                prompt_len = len(prompt_ids)\\n\"\n",
        "        \"                full_len = len(full_ids)\\n\"\n",
        "        \"            else:\\n\"\n",
        "        \"                skipped_too_long += 1\\n\"\n",
        "        \"                continue\"\n",
        "    )\n",
        "    if old_trunc in l_code:\n",
        "        l_code = l_code.replace(old_trunc, new_trunc, 1)\n",
        "        lora_script.write_text(l_code, encoding='utf-8')\n",
        "        print('🔧 Đã cập nhật cơ chế giữ 100% Code + Schema + Question (1,109/1,109 mẫu) tại MAX_SEQ_LEN=2560.')\n",
        "\n",
        "# 3. Tự động vá scripts/train_sft_kaggle_2t4_reasoning.py trên đĩa\n",
        "train_script = REPO_DIR / 'scripts' / 'train_sft_kaggle_2t4_reasoning.py'\n",
        "if train_script.is_file():\n",
        "    code = train_script.read_text(encoding='utf-8').replace('\\r\\n', '\\n')\n",
        "    code = code.replace('warmup_ratio=0.05', 'warmup_steps=5')\n",
        "    code = code.replace('min(args.max_seq_len, 7500)', 'min(args.max_seq_len, 2560)')\n",
        "    code = code.replace(\n",
        "        '        def _fsdp_qlora_plugin_updates(self):\\n            super()._fsdp_qlora_plugin_updates()',\n",
        "        '        def _fsdp_qlora_plugin_updates(self):\\n            if hasattr(super(), \"_fsdp_qlora_plugin_updates\"):\\n                super()._fsdp_qlora_plugin_updates()'\n",
        "    )\n",
        "    old_peft_blk = (\n",
        "        \"    if args.init_adapter:\\n\"\n",
        "        \"        # Continue fine-tuning from an existing LoRA adapter (r/alpha/targets come from its adapter_config.json)\\n\"\n",
        "        \"        from peft import PeftModel\\n\"\n",
        "        \"        model = PeftModel.from_pretrained(model, args.init_adapter, is_trainable=True)\\n\"\n",
        "        \"    else:\\n\"\n",
        "        \"        model = get_peft_model(model, LoraConfig(\\n\"\n",
        "        \"            task_type=TaskType.CAUSAL_LM, r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.0, bias='none',\\n\"\n",
        "        \"            target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']))\"\n",
        "    )\n",
        "    new_peft_blk = (\n",
        "        \"    model = get_peft_model(model, LoraConfig(\\n\"\n",
        "        \"        task_type=TaskType.CAUSAL_LM, r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.0, bias='none',\\n\"\n",
        "        \"        target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']))\\n\"\n",
        "        \"    if args.init_adapter:\\n\"\n",
        "        \"        from safetensors.torch import load_file\\n\"\n",
        "        \"        from peft import set_peft_model_state_dict\\n\"\n",
        "        \"        adapter_dir = Path(args.init_adapter)\\n\"\n",
        "        \"        if (adapter_dir / 'repaired' / 'adapter_model.safetensors').is_file():\\n\"\n",
        "        \"            adapter_dir = adapter_dir / 'repaired'\\n\"\n",
        "        \"        init_state = load_file(str(adapter_dir / 'adapter_model.safetensors'), device='cpu')\\n\"\n",
        "        \"        init_state = {k.replace('_checkpoint_wrapped_module.', ''): v for k, v in init_state.items()}\\n\"\n",
        "        \"        result = set_peft_model_state_dict(model, init_state)\\n\"\n",
        "        \"        unexpected = getattr(result, 'unexpected_keys', [])\\n\"\n",
        "        \"        if unexpected:\\n\"\n",
        "        \"            raise ValueError(f'--init-adapter has {len(unexpected)} unexpected keys, e.g. {unexpected[:3]}')\\n\"\n",
        "        \"        if main:\\n\"\n",
        "        \"            print(f'Warm-started LoRA from {adapter_dir} ({len(init_state)} tensors)', flush=True)\"\n",
        "    )\n",
        "    if old_peft_blk in code:\n",
        "        code = code.replace(old_peft_blk, new_peft_blk, 1)\n",
        "    train_script.write_text(code, encoding='utf-8')\n",
        "\n",
        "if RUN_SMOKE:\n",
        "    SMOKE_DIR = WORK_DIR / 'outputs' / f'{RUN_NAME}_smoke'\n",
        "    shutil.rmtree(SMOKE_DIR, ignore_errors=True)\n",
        "    smoke_cmd = [\n",
        "        sys.executable, '-m', 'accelerate.commands.launch',\n",
        "        '--config_file', 'configs/accelerate_kaggle_2t4_sft.yaml',\n",
        "        'scripts/train_sft_kaggle_2t4_reasoning.py',\n",
        "        '--model', str(LOCAL_MODEL_DIR),\n",
        "        '--data', str(DATA_PATH),\n",
        "        '--data-dir', str(DATA_DIR),\n",
        "        '--output-dir', str(SMOKE_DIR),\n",
        "        '--max-seq-len', str(MAX_SEQ_LEN),\n",
        "        '--grad-accum', '1',\n",
        "        '--lr', str(LEARNING_RATE),\n",
        "        '--lora-r', str(LORA_R),\n",
        "        '--lora-alpha', str(LORA_ALPHA),\n",
        "        '--load-in-4bit',\n",
        "        '--completion-format', 'chat',\n",
        "        '--smoke',\n",
        "    ]\n",
        "    if INIT_ADAPTER_LOCAL_DIR is not None:\n",
        "        smoke_cmd.extend(['--init-adapter', str(INIT_ADAPTER_LOCAL_DIR)])\n",
        "\n",
        "    smoke_env = os.environ.copy()\n",
        "    smoke_env.pop('DATAMATE_HF_REPO', None)\n",
        "    smoke_env.pop('DATAMATE_HF_PREFIX', None)\n",
        "\n",
        "    print(f'🧪 Đang chạy Smoke Test 2 steps trên 2x T4 (seq_len={MAX_SEQ_LEN})...')\n",
        "    proc = subprocess.Popen(\n",
        "        smoke_cmd, cwd=str(REPO_DIR), env=smoke_env,\n",
        "        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,\n",
        "        text=True, bufsize=1,\n",
        "    )\n",
        "    log_tail = []\n",
        "    for line in proc.stdout:\n",
        "        print(line, end='', flush=True)\n",
        "        log_tail.append(line)\n",
        "        if len(log_tail) > 60:\n",
        "            log_tail.pop(0)\n",
        "    rc = proc.wait()\n",
        "    assert rc == 0, f'❌ Smoke test thất bại với mã lỗi {rc}.\\n--- CHI TIẾT LỖI CUỐI LOG ---\\n' + ''.join(log_tail[-45:])\n",
        "    shutil.rmtree(SMOKE_DIR, ignore_errors=True)\n",
        "    print(f'\\n✅ Smoke Test thành công! VRAM hoàn toàn ổn định với seq_len={MAX_SEQ_LEN} trên 2x T4.')\n",
        "else:\n",
        "    print('⏭️ Bỏ qua Smoke Test (RUN_SMOKE=False).')\n",
    ]
    train_cell5_lines = [
        "# ==============================================================================\n",
        "# CELL 5: CHẠY HUẤN LUYỆN CHÍNH THỨC (DIRECT CODER FULL TRAINING)\n",
        "# ==============================================================================\n",
        "import os\n",
        "import subprocess\n",
        "import sys\n",
        "from huggingface_hub import HfApi\n",
        "\n",
        "MAX_SEQ_LEN = 2560\n",
        "try:\n",
        "    HfApi(token=os.environ['HF_TOKEN']).create_repo(repo_id=HF_REPO, repo_type='model', private=True, exist_ok=True)\n",
        "except Exception:\n",
        "    pass\n",
        "\n",
        "train_cmd = [\n",
        "    sys.executable, '-m', 'accelerate.commands.launch',\n",
        "    '--config_file', 'configs/accelerate_kaggle_2t4_sft.yaml',\n",
        "    'scripts/train_sft_kaggle_2t4_reasoning.py',\n",
        "    '--model', str(LOCAL_MODEL_DIR),\n",
        "    '--data', str(DATA_PATH),\n",
        "    '--data-dir', str(DATA_DIR),\n",
        "    '--output-dir', str(OUT_DIR),\n",
        "    '--max-seq-len', str(MAX_SEQ_LEN),\n",
        "    '--epochs', str(EPOCHS),\n",
        "    '--grad-accum', str(GRAD_ACCUM),\n",
        "    '--lr', str(LEARNING_RATE),\n",
        "    '--lora-r', str(LORA_R),\n",
        "    '--lora-alpha', str(LORA_ALPHA),\n",
        "    '--load-in-4bit',\n",
        "    '--completion-format', 'chat',\n",
        "]\n",
        "if INIT_ADAPTER_LOCAL_DIR is not None:\n",
        "    train_cmd.extend(['--init-adapter', str(INIT_ADAPTER_LOCAL_DIR)])\n",
        "if RESUME_CHECKPOINT:\n",
        "    train_cmd.extend(['--resume', RESUME_CHECKPOINT])\n",
        "\n",
        "print('🔥 Bắt đầu huấn luyện Direct Coder LoRA trên 2x T4:', ' '.join(train_cmd))\n",
        "proc = subprocess.Popen(\n",
        "    train_cmd, cwd=str(REPO_DIR),\n",
        "    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,\n",
        "    text=True, bufsize=1,\n",
        ")\n",
        "log_tail = []\n",
        "for line in proc.stdout:\n",
        "    print(line, end='', flush=True)\n",
        "    log_tail.append(line)\n",
        "    if len(log_tail) > 60:\n",
        "        log_tail.pop(0)\n",
        "rc = proc.wait()\n",
        "assert rc == 0, f'❌ Quá trình huấn luyện dừng với mã lỗi {rc}.\\n--- CHI TIẾT LỖI CUỐI LOG ---\\n' + ''.join(log_tail[-45:])\n",
        "print('\\n🎉 ĐÃ HOÀN TẤT HUẤN LUYỆN DIRECT CODER LORA!')\n",
    ]
    for c in tnb["cells"]:
        if c.get("id") == "train_cell1_config":
            c["source"] = [line.replace("MAX_SEQ_LEN   = 8192", "MAX_SEQ_LEN   = 2560") for line in c["source"]]
        elif c.get("id") == "train_cell2_deps":
            c["source"] = train_cell2_lines
        elif c.get("id") == "train_cell4_smoke":
            c["source"] = train_cell4_lines
        elif c.get("id") == "train_cell5_full_train":
            c["source"] = train_cell5_lines
    train_nb_path.write_text(json.dumps(tnb, ensure_ascii=False, indent=1), encoding="utf-8")
    print("✅ Updated notebooks/Train_Qwen25_14B_1M_Reasoning_Kaggle_2T4.ipynb")

# Ensure Evaluate notebook Cell 3, Cell 4 and Cell 5 support fast vLLM 0.10.2 dual-shard on 2x T4 (+ fallback Transformers)
nb_path = ROOT / "notebooks" / "Evaluate_Qwen25_14B_1M_Reasoning_Kaggle_2T4.ipynb"
if nb_path.exists():
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    cell3_lines = [
        "# ==============================================================================\n",
        "# CELL 3: TẠO MÔI TRƯỜNG SẠCH /tmp/vllm_eval_env (vLLM 0.10.2 + T4 SDPA FALLBACK)\n",
        "# ==============================================================================\n",
        "import os\n",
        "import shutil\n",
        "import subprocess\n",
        "import sys\n",
        "from pathlib import Path\n",
        "\n",
        "VLLM_VENV = Path('/tmp/vllm_eval_env')\n",
        "VLLM_PY = VLLM_VENV / 'bin' / 'python'\n",
        "HAS_VLLM = False\n",
        "VLLM_LD_LIBRARY_PATH = os.environ.get('LD_LIBRARY_PATH', '')\n",
        "\n",
        "def _pip_install(target_py, pkgs):\n",
        "    base = [sys.executable, '-m', 'pip', '--python', str(target_py), 'install', '-q', '--no-cache-dir', '--upgrade']\n",
        "    try:\n",
        "        subprocess.check_call(base + pkgs)\n",
        "    except subprocess.CalledProcessError:\n",
        "        subprocess.check_call(base + ['--break-system-packages'] + pkgs)\n",
        "\n",
        "pinned_common = [\n",
        "    'transformers==4.57.1',\n",
        "    'peft==0.17.1',\n",
        "    'accelerate==1.11.0',\n",
        "    'huggingface-hub==0.36.2',\n",
        "    'tokenizers==0.22.2',\n",
        "    'bitsandbytes==0.48.1',\n",
        "    'safetensors>=0.4.5',\n",
        "    'pyyaml>=6.0',\n",
        "    'psutil>=5.9',\n",
        "    'tqdm',\n",
        "    'pandas',\n",
        "    'numpy',\n",
        "    'openpyxl',\n",
        "    'python-calamine',\n",
        "    'xlrd',\n",
        "    'duckdb',\n",
        "]\n",
        "\n",
        "try:\n",
        "    if not VLLM_PY.is_file():\n",
        "        print(f'📦 Tạo venv sạch bằng --without-pip tại {VLLM_VENV} (tránh lỗi ensurepip Python {sys.version.split()[0]})...')\n",
        "        subprocess.check_call([sys.executable, '-m', 'venv', '--without-pip', str(VLLM_VENV)])\n",
        "    print('⚡ Đang cài đặt vllm==0.10.2 (cp38-abi3, hỗ trợ Python 3.13) + bộ thư viện chuẩn...')\n",
        "    _pip_install(VLLM_PY, ['wrapt'])\n",
        "    _pip_install(VLLM_PY, [\n",
        "        'vllm==0.10.2',\n",
        "        'nvidia-cusparselt-cu12',\n",
        "        'pydantic>=2.11.7',\n",
        "        *pinned_common,\n",
        "    ])\n",
        "\n",
        "    lib_dirs = sorted({str(p.parent) for p in VLLM_VENV.glob('lib/python*/site-packages/nvidia/**/*.so*')})\n",
        "    VLLM_LD_LIBRARY_PATH = ':'.join(filter(None, [*lib_dirs, os.environ.get('LD_LIBRARY_PATH', '')]))\n",
        "\n",
        "    check_env = os.environ.copy()\n",
        "    check_env['LD_LIBRARY_PATH'] = VLLM_LD_LIBRARY_PATH\n",
        "    check_env.pop('VLLM_ATTENTION_BACKEND', None)\n",
        "    check_code = (\n",
        "        'import torch, vllm, transformers, peft, accelerate, bitsandbytes, pandas, openpyxl, xlrd, duckdb; '\n",
        "        'from transformers.integrations import sdpa_attention; '\n",
        "        'assert transformers.__version__ == \"4.57.1\", transformers.__version__; '\n",
        "        'assert hasattr(sdpa_attention, \"use_gqa_in_sdpa\"); '\n",
        "        'print(f\"{vllm.__version__}|{transformers.__version__}|{peft.__version__}|gpus={torch.cuda.device_count()}\")'\n",
        "    )\n",
        "    ver_out = subprocess.check_output([str(VLLM_PY), '-c', check_code], env=check_env, text=True).strip()\n",
        "    HAS_VLLM = True\n",
        "    print(f'🚀 vLLM sẵn sàng: {ver_out} | VLLM_PY={VLLM_PY}')\n",
        "except Exception as exc:\n",
        "    print(f'⚠️ Không khởi tạo được vLLM ({exc}). Chuyển về fallback Transformers T4 SDPA...')\n",
        "    shutil.rmtree(VLLM_VENV, ignore_errors=True)\n",
        "    VLLM_PY = Path(sys.executable)\n",
        "    HAS_VLLM = False\n",
        "    _pip_install(VLLM_PY, ['wrapt', *pinned_common])\n",
        "    ver_out = subprocess.check_output(\n",
        "        [str(VLLM_PY), '-c', 'import transformers, peft, accelerate; from transformers.integrations import sdpa_attention; assert hasattr(sdpa_attention, \"use_gqa_in_sdpa\"); print(transformers.__version__)'],\n",
        "        text=True,\n",
        "    ).strip()\n",
        "    print(f'✅ Fallback Transformers sẵn sàng: transformers={ver_out}, HAS_VLLM={HAS_VLLM}')\n",
    ]
    cell4_lines = [
        "# ==============================================================================\n",
        "# CELL 4: CHẠY ĐÁNH GIÁ DUAL-GPU TRÊN 2x T4 (ƯU TIÊN vLLM 2 SHARD SONG SONG)\n",
        "# ==============================================================================\n",
        "import json\n",
        "import os\n",
        "import shutil\n",
        "import subprocess\n",
        "import sys\n",
        "import time\n",
        "from collections import deque\n",
        "from pathlib import Path\n",
        "import torch\n",
        "\n",
        "# 0. Vá sẵn src/agent/solver.py (T4 SDPA + Chunked Prefill 512) cho đường fallback Transformers\n",
        "solver_py = REPO_DIR / 'src' / 'agent' / 'solver.py'\n",
        "if solver_py.exists():\n",
        "    s_txt = solver_py.read_text(encoding='utf-8').replace('\\r\\n', '\\n')\n",
        "    if '_greedy_chunked' not in s_txt:\n",
        "        old_init = '        logger.info(\"Initializing offline Transformers backend with model path: %s\", model_path)\\n        torch_dtype = getattr(torch, dtype_str) if hasattr(torch, dtype_str) else torch.float16'\n",
        "        new_init = (\n",
        "            '        logger.info(\"Initializing offline Transformers backend with model path: %s\", model_path)\\n'\n",
        "            '        try:\\n'\n",
        "            '            from src.coder_training.t4_attention import configure_t4_sdpa\\n'\n",
        "            '            configure_t4_sdpa()\\n'\n",
        "            '        except Exception as exc:\\n'\n",
        "            '            logger.debug(\"T4 SDPA configuration skipped: %s\", exc)\\n'\n",
        "            '        torch_dtype = getattr(torch, dtype_str) if hasattr(torch, dtype_str) else torch.float16'\n",
        "        )\n",
        "        if old_init in s_txt:\n",
        "            s_txt = s_txt.replace(old_init, new_init, 1)\n",
        "        old_gen = (\n",
        "            '        inputs = inputs.to(self.model.device)\\n'\n",
        "            '        with torch.inference_mode():\\n'\n",
        "            '            gen_kwargs = {'\n",
        "        )\n",
        "        new_gen = (\n",
        "            '        if self.temperature <= 0.0 and hasattr(self.model, \"generation_config\") and callable(self.model):\\n'\n",
        "            '            with torch.inference_mode():\\n'\n",
        "            '                generated_ids = self._greedy_chunked(inputs.input_ids, generation_tokens, prefill_chunk=512)\\n'\n",
        "            '            return self.tokenizer.decode(generated_ids, skip_special_tokens=True)\\n\\n'\n",
        "            '        inputs = inputs.to(self.model.device)\\n'\n",
        "            '        with torch.inference_mode():\\n'\n",
        "            '            gen_kwargs = {'\n",
        "        )\n",
        "        assert old_gen in s_txt, 'Không tìm thấy khối generate trong solver.py'\n",
        "        s_txt = s_txt.replace(old_gen, new_gen, 1)\n",
        "        chunked_method = '''\n",
        "    def _greedy_chunked(self, input_ids: Any, max_new_tokens: int, prefill_chunk: int = 512) -> List[int]:\n",
        "        import gc\n",
        "        import time\n",
        "        import torch\n",
        "        from transformers import DynamicCache\n",
        "\n",
        "        model = self.model\n",
        "        device = model.device\n",
        "        ids = input_ids.to(device)\n",
        "        eos = getattr(model.generation_config, \"eos_token_id\", None)\n",
        "        eos_ids = set(eos if isinstance(eos, (list, tuple)) else [eos]) if eos is not None else set()\n",
        "        if self.tokenizer.eos_token_id is not None:\n",
        "            eos_ids.add(self.tokenizer.eos_token_id)\n",
        "\n",
        "        cache = DynamicCache()\n",
        "        out = None\n",
        "        generated: List[int] = []\n",
        "\n",
        "        def _forward_step(chunk_ids: Any) -> Any:\n",
        "            try:\n",
        "                return model(input_ids=chunk_ids, past_key_values=cache, use_cache=True, logits_to_keep=1)\n",
        "            except TypeError:\n",
        "                return model(input_ids=chunk_ids, past_key_values=cache, use_cache=True)\n",
        "\n",
        "        try:\n",
        "            total = int(ids.shape[1])\n",
        "            for start in range(0, total, prefill_chunk):\n",
        "                out = _forward_step(ids[:, start : start + prefill_chunk])\n",
        "                if getattr(out, \"past_key_values\", None) is not None:\n",
        "                    cache = out.past_key_values\n",
        "            started = time.time()\n",
        "            for _ in range(max_new_tokens):\n",
        "                next_id = int(out.logits[0, -1].argmax())\n",
        "                if next_id in eos_ids:\n",
        "                    break\n",
        "                generated.append(next_id)\n",
        "                if self.max_generation_time_sec is not None and (time.time() - started) > self.max_generation_time_sec:\n",
        "                    break\n",
        "                out = _forward_step(torch.tensor([[next_id]], device=device, dtype=ids.dtype))\n",
        "                if getattr(out, \"past_key_values\", None) is not None:\n",
        "                    cache = out.past_key_values\n",
        "            return generated\n",
        "        finally:\n",
        "            del out, cache, ids\n",
        "            gc.collect()\n",
        "            if torch.cuda.is_available():\n",
        "                torch.cuda.empty_cache()\n",
        "'''\n",
        "        marker = '\\n\\nclass DryRunBackend(BaseInferenceBackend):'\n",
        "        assert marker in s_txt, 'Không tìm thấy DryRunBackend trong solver.py'\n",
        "        s_txt = s_txt.replace(marker, chunked_method + marker, 1)\n",
        "        solver_py.write_text(s_txt, encoding='utf-8')\n",
        "        print('🔧 Đã vá sẵn T4 SDPA + Chunked Prefill (512 tokens) vào src/agent/solver.py.')\n",
        "\n",
        "QUESTIONS_FILE = REPO_DIR / 'dev' / 'questions.jsonl'\n",
        "GOLD_FILE      = REPO_DIR / 'dev' / 'gold.jsonl'\n",
        "DATA_DIR       = REPO_DIR / 'data' / 'train'\n",
        "\n",
        "EVAL_OUT_DIR.mkdir(parents=True, exist_ok=True)\n",
        "backend_mode = 'vllm' if globals().get('HAS_VLLM', False) else 'transformers'\n",
        "num_gpus = max(1, torch.cuda.device_count())\n",
        "\n",
        "print('=' * 68)\n",
        "print('🚀 BẮT ĐẦU ĐÁNH GIÁ TRÊN 30 CÂU UNSEEN DEV')\n",
        "print(f'⚙️ Backend       : {backend_mode}')\n",
        "print(f'🧠 Model         : {BASE_MODEL_ID}')\n",
        "print(f'🎯 Adapter       : {EVAL_ADAPTER_DIR.name}')\n",
        "print(f'📏 Context Window: {MAX_MODEL_LEN} | Max New Tokens: {MAX_TOKENS}')\n",
        "print(f'🔥 GPU Cores     : {num_gpus}x T4')\n",
        "print('=' * 68)\n",
        "\n",
        "run_transformers = (backend_mode != 'vllm')\n",
        "if backend_mode == 'vllm':\n",
        "    # Chia 30 câu thành N shard độc lập chạy song song trên từng T4 (TP=1, 4-bit -> không bị OOM FP16 14.2GB như TP=2)\n",
        "    all_q = [json.loads(l) for l in QUESTIONS_FILE.read_text(encoding='utf-8').splitlines() if l.strip()]\n",
        "    all_g = {g['id']: g for g in (json.loads(l) for l in GOLD_FILE.read_text(encoding='utf-8').splitlines() if l.strip())}\n",
        "    NUM_SHARDS = min(num_gpus, len(all_q))\n",
        "    vllm_gpu_util = min(float(GPU_MEM_UTIL), 0.92)\n",
        "\n",
        "    base_env = os.environ.copy()\n",
        "    base_env['VLLM_USE_V1'] = '1'\n",
        "    base_env['VLLM_WORKER_MULTIPROC_METHOD'] = 'spawn'\n",
        "    base_env['VLLM_NO_USAGE_STATS'] = '1'\n",
        "    base_env['TOKENIZERS_PARALLELISM'] = 'false'\n",
        "    base_env.pop('VLLM_ATTENTION_BACKEND', None)\n",
        "    base_env.pop('PYTORCH_CUDA_ALLOC_CONF', None)\n",
        "    base_env.pop('PYTORCH_ALLOC_CONF', None)\n",
        "    if globals().get('VLLM_LD_LIBRARY_PATH'):\n",
        "        base_env['LD_LIBRARY_PATH'] = VLLM_LD_LIBRARY_PATH\n",
        "\n",
        "    procs = []\n",
        "    for idx in range(NUM_SHARDS):\n",
        "        shard_dir = EVAL_OUT_DIR / f'shard{idx}'\n",
        "        shard_dir.mkdir(parents=True, exist_ok=True)\n",
        "        qs = all_q[idx::NUM_SHARDS]\n",
        "        (shard_dir / 'questions.jsonl').write_text(\n",
        "            ''.join(json.dumps(q, ensure_ascii=False) + '\\n' for q in qs), encoding='utf-8'\n",
        "        )\n",
        "        (shard_dir / 'gold.jsonl').write_text(\n",
        "            ''.join(json.dumps(all_g[q['id']], ensure_ascii=False) + '\\n' for q in qs), encoding='utf-8'\n",
        "        )\n",
        "        cmd = [\n",
        "            str(VLLM_PY), '-u', 'scripts/evaluate_pilot_30.py',\n",
        "            '--base-model', str(LOCAL_MODEL_DIR),\n",
        "            '--adapter-dir', str(EVAL_ADAPTER_DIR),\n",
        "            '--questions-file', str(shard_dir / 'questions.jsonl'),\n",
        "            '--gold-file', str(shard_dir / 'gold.jsonl'),\n",
        "            '--data-dir', str(DATA_DIR),\n",
        "            '--output-dir', str(shard_dir / 'out'),\n",
        "            '--backend', 'vllm',\n",
        "            '--dtype', 'float16',\n",
        "            '--load-in-4bit',\n",
        "            '--tensor-parallel-size', '1',\n",
        "            '--gpu-memory-utilization', str(vllm_gpu_util),\n",
        "            '--max-num-seqs', '1',\n",
        "            '--enforce-eager',\n",
        "            '--no-prefix-caching',\n",
        "            '--max-model-len', str(MAX_MODEL_LEN),\n",
        "            '--max-tokens', str(MAX_TOKENS),\n",
        "            '--prompt-format', 'system-user',\n",
        "            '--prompt-variant', 'baseline',\n",
        "        ]\n",
        "        env_i = dict(base_env, CUDA_VISIBLE_DEVICES=str(idx))\n",
        "        log_f = open(shard_dir / 'run.log', 'w', encoding='utf-8')\n",
        "        print(f'🚀 Shard {idx}: chạy {len(qs)} câu trên GPU {idx} (vLLM TP=1 4-bit, util={vllm_gpu_util})')\n",
        "        p = subprocess.Popen(cmd, cwd=str(REPO_DIR), env=env_i, stdout=log_f, stderr=subprocess.STDOUT)\n",
        "        procs.append((p, log_f, shard_dir))\n",
        "        if idx + 1 < NUM_SHARDS:\n",
        "            time.sleep(35)\n",
        "\n",
        "    while any(p.poll() is None for p, _, _ in procs):\n",
        "        time.sleep(30)\n",
        "        parts = []\n",
        "        for i, (p, _, d) in enumerate(procs):\n",
        "            log_txt = (d / 'run.log').read_text(encoding='utf-8', errors='ignore').replace('\\r', '\\n')\n",
        "            last_ln = ([ln for ln in log_txt.splitlines() if ln.strip()] or ['...'])[-1][:110]\n",
        "            done_cnt = len(list((d / 'out' / 'logs').glob('*.json'))) if (d / 'out' / 'logs').is_dir() else 0\n",
        "            parts.append(f'[shard{i} rc={p.poll()} done={done_cnt}] {last_ln}')\n",
        "        print(' | '.join(parts), flush=True)\n",
        "\n",
        "    for _, log_f, _ in procs:\n",
        "        log_f.close()\n",
        "\n",
        "    bad = [d for p, _, d in procs if p.returncode != 0]\n",
        "    if bad:\n",
        "        err_blocks = []\n",
        "        for d in bad:\n",
        "            tail = '\\n'.join((d / 'run.log').read_text(encoding='utf-8', errors='ignore').splitlines()[-45:])\n",
        "            err_blocks.append(f'=== {d.name} LAST 45 LINES ===\\n{tail}')\n",
        "        print('\\n'.join(err_blocks))\n",
        "        has_progress = any((d / 'out' / 'logs').is_dir() and any((d / 'out' / 'logs').glob('*.json')) for _, _, d in procs)\n",
        "        if has_progress:\n",
        "            raise RuntimeError(f'❌ vLLM shard thất bại giữa chừng: {[d.name for d in bad]}')\n",
        "        print('⚠️ vLLM thất bại lúc khởi tạo -> Tự động chuyển sang fallback Transformers T4 SDPA!')\n",
        "        run_transformers = True\n",
        "    else:\n",
        "        # Gộp predictions, logs và report cho Cell 5\n",
        "        logs_merged = EVAL_OUT_DIR / 'logs'\n",
        "        logs_merged.mkdir(parents=True, exist_ok=True)\n",
        "        pred_by_id = {}\n",
        "        reps = []\n",
        "        for _, _, d in procs:\n",
        "            out_d = d / 'out'\n",
        "            reps.append(json.loads((out_d / 'evaluation_report.json').read_text(encoding='utf-8')))\n",
        "            for ln in (out_d / 'submission.jsonl').read_text(encoding='utf-8').splitlines():\n",
        "                if ln.strip():\n",
        "                    row = json.loads(ln)\n",
        "                    pred_by_id[row.get('id') or row.get('question_id')] = ln\n",
        "            for lf in (out_d / 'logs').glob('*.json'):\n",
        "                shutil.copy2(lf, logs_merged / lf.name)\n",
        "\n",
        "        (EVAL_OUT_DIR / 'submission.jsonl').write_text(\n",
        "            ''.join(pred_by_id[q['id']] + '\\n' for q in all_q if q['id'] in pred_by_id),\n",
        "            encoding='utf-8',\n",
        "        )\n",
        "        total = sum(int(r['total_questions']) for r in reps)\n",
        "        correct = sum(int(r['correct']) for r in reps)\n",
        "        wrong = sum(int(r['wrong']) for r in reps)\n",
        "        abstain = sum(int(r['abstain']) for r in reps)\n",
        "        wall = max(float(r.get('inference_seconds') or 0.0) for r in reps)\n",
        "        pa = (correct - wrong) / total if total else 0.0\n",
        "        merged_report = {\n",
        "            'model_id': BASE_MODEL_ID,\n",
        "            'adapter_path': str(EVAL_ADAPTER_DIR),\n",
        "            'backend': 'vllm_dual_shard',\n",
        "            'prompt_variant': 'baseline',\n",
        "            'max_model_len': MAX_MODEL_LEN,\n",
        "            'total_questions': total,\n",
        "            'correct': correct,\n",
        "            'wrong': wrong,\n",
        "            'abstain': abstain,\n",
        "            'penalized_accuracy': pa,\n",
        "            'inference_seconds': wall,\n",
        "            'seconds_per_question': wall / total if total else None,\n",
        "            'shards': reps,\n",
        "        }\n",
        "        (EVAL_OUT_DIR / 'evaluation_report.json').write_text(\n",
        "            json.dumps(merged_report, ensure_ascii=False, indent=2),\n",
        "            encoding='utf-8',\n",
        "        )\n",
        "        print('=' * 68)\n",
        "        print(f'📊 TỔNG KẾT DUAL-GPU vLLM ({total} câu): PA = {pa:+.4f} (+{correct} / -{wrong} / 0:{abstain}) | Wall = {wall:.1f}s')\n",
        "        print('=' * 68)\n",
        "if run_transformers:\n",
        "    cmd = [\n",
        "        str(VLLM_PY), 'scripts/evaluate_pilot_30.py',\n",
        "        '--base-model', str(LOCAL_MODEL_DIR),\n",
        "        '--adapter-dir', str(EVAL_ADAPTER_DIR),\n",
        "        '--questions-file', str(QUESTIONS_FILE),\n",
        "        '--gold-file', str(GOLD_FILE),\n",
        "        '--data-dir', str(DATA_DIR),\n",
        "        '--output-dir', str(EVAL_OUT_DIR),\n",
        "        '--backend', 'transformers',\n",
        "        '--dtype', 'float16',\n",
        "        '--load-in-4bit',\n",
        "        '--attn-implementation', 'sdpa',\n",
        "        '--device-map', 'auto',\n",
        "        '--max-model-len', str(MAX_MODEL_LEN),\n",
        "        '--max-tokens', str(MAX_TOKENS),\n",
        "        '--prompt-format', 'system-user',\n",
        "        '--prompt-variant', 'baseline',\n",
        "    ]\n",
        "    env = os.environ.copy()\n",
        "    env['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'\n",
        "    if globals().get('VLLM_LD_LIBRARY_PATH'):\n",
        "        env['LD_LIBRARY_PATH'] = VLLM_LD_LIBRARY_PATH\n",
        "    proc = subprocess.Popen(\n",
        "        cmd,\n",
        "        cwd=str(REPO_DIR),\n",
        "        env=env,\n",
        "        stdout=subprocess.PIPE,\n",
        "        stderr=subprocess.STDOUT,\n",
        "        text=True,\n",
        "        bufsize=1,\n",
        "    )\n",
        "    log_tail = deque(maxlen=45)\n",
        "    for line in proc.stdout:\n",
        "        print(line, end='', flush=True)\n",
        "        log_tail.append(line)\n",
        "    rc = proc.wait()\n",
        "    assert rc == 0, f'❌ Đánh giá thất bại với mã lỗi {rc}\\n--- LAST 45 LINES ---\\n' + ''.join(log_tail)\n",
        "\n",
        "print('\\n🎉 HOÀN TẤT ĐÁNH GIÁ TOÀN DIỆN!')\n",
    ]
    cell5_lines = [
        "# ==============================================================================\n",
        "# CELL 5: ĐẨY BÁO CÁO ĐÁNH GIÁ, SUBMISSION & LOGS LÊN HUGGING FACE HUB\n",
        "# ==============================================================================\n",
        "import json\n",
        "import os\n",
        "from huggingface_hub import HfApi\n",
        "\n",
        "report_file = EVAL_OUT_DIR / 'evaluation_report.json'\n",
        "if not report_file.is_file():\n",
        "    report_file = EVAL_OUT_DIR / 'eval_summary.json'\n",
        "assert report_file.is_file(), f'❌ Không tìm thấy báo cáo đánh giá trong {EVAL_OUT_DIR}'\n",
        "summary_data = json.loads(report_file.read_text(encoding='utf-8'))\n",
        "pa_score = float(summary_data.get('penalized_accuracy', 0.0))\n",
        "n_corr = int(summary_data.get('correct', summary_data.get('num_correct', 0)))\n",
        "n_wrong = int(summary_data.get('wrong', summary_data.get('num_wrong', 0)))\n",
        "n_abst = int(summary_data.get('abstain', summary_data.get('num_abstained', 0)))\n",
        "\n",
        "api = HfApi(token=os.environ.get('HF_TOKEN') or None)\n",
        "remote_eval_path = f'{ADAPTER_RUN_PREFIX}/eval_dev_30_ctx{MAX_MODEL_LEN}_{EVAL_TIMESTAMP}'\n",
        "\n",
        "api.upload_folder(\n",
        "    repo_id=HF_REPO,\n",
        "    repo_type='model',\n",
        "    folder_path=str(EVAL_OUT_DIR),\n",
        "    path_in_repo=remote_eval_path,\n",
        "    commit_message=(\n",
        "        f'Eval 30 unseen dev (ctx={MAX_MODEL_LEN}): PA={pa_score:+.4f} '\n",
        "        f'(+{n_corr}/-{n_wrong}/0:{n_abst})'\n",
        "    ),\n",
        ")\n",
        "print(f'🎉 Đã lưu toàn bộ kết quả đánh giá lên: https://huggingface.co/{HF_REPO}/tree/main/{remote_eval_path}')\n",
    ]
    for c in nb["cells"]:
        if c.get("id") == "eval_cell3_venv_and_patch":
            c["source"] = cell3_lines
        elif c.get("id") == "eval_cell4_run_dual_gpu":
            c["source"] = cell4_lines
        elif c.get("id") == "eval_cell5_upload":
            c["source"] = cell5_lines
    nb_path.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print("✅ Updated notebooks/Evaluate_Qwen25_14B_1M_Reasoning_Kaggle_2T4.ipynb")

BUNDLE_ZIP = ROOT / "result" / "r1_reasoning_kaggle_bundle.zip"
BUNDLE_ZIP.parent.mkdir(parents=True, exist_ok=True)

print(f"📦 Packaging bundle to: {BUNDLE_ZIP}")
if BUNDLE_ZIP.exists():
    BUNDLE_ZIP.unlink()

with zipfile.ZipFile(BUNDLE_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    # 1. src/
    print("  + Adding src/...")
    for p in (ROOT / "src").rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        zf.write(p, rel)

    # 2. scripts/
    print("  + Adding scripts/...")
    for p in (ROOT / "scripts").glob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        zf.write(p, rel)

    # 3. configs/
    print("  + Adding configs/...")
    for p in (ROOT / "configs").glob("*.yaml"):
        rel = p.relative_to(ROOT).as_posix()
        zf.write(p, rel)

    # 4. SFT Dataset (0% thinking, 100% pure python code, full rulebook)
    sft_file = ROOT / "result" / "deepseek_r1_1109_sft_train_ready.jsonl"
    if sft_file.exists():
        print(f"  + Adding SFT dataset: {sft_file.name} ({sft_file.stat().st_size / (1024*1024):.2f} MB)...")
        zf.write(sft_file, "result/deepseek_r1_1109_sft_train_ready.jsonl")

    # 5. dev/ 30 evaluation set
    dev_q = ROOT / "result" / "unseen_eval_30" / "questions.jsonl"
    dev_g = ROOT / "eval_gold" / "unseen_gold_30.jsonl"
    if dev_q.exists():
        print("  + Adding dev/questions.jsonl...")
        zf.write(dev_q, "dev/questions.jsonl")
    if dev_g.exists():
        print("  + Adding dev/gold.jsonl...")
        zf.write(dev_g, "dev/gold.jsonl")

    # 6. data/train/
    print("  + Adding data/train/...")
    for p in (ROOT / "data" / "train").rglob("*"):
        if p.is_file() and not p.name.startswith("."):
            rel = p.relative_to(ROOT).as_posix()
            zf.write(p, rel)

zip_size_mb = BUNDLE_ZIP.stat().st_size / (1024 * 1024)
print(f"✅ Created bundle: {BUNDLE_ZIP.name} ({zip_size_mb:.2f} MB)")

# Upload to Hugging Face
token = os.environ.get("HF_TOKEN") or get_token()
assert token, "❌ Hugging Face token not found!"
api = HfApi(token=token)

TARGET_REPO = "Crinkk/Zalo-challenge"
print(f"\n🚀 Uploading bundle to Hugging Face repo: {TARGET_REPO}...")

# 1. Ensure both model and dataset repos exist
api.create_repo(repo_id=TARGET_REPO, repo_type="model", private=False, exist_ok=True)
api.create_repo(repo_id=TARGET_REPO, repo_type="dataset", private=False, exist_ok=True)

filenames_to_upload = [
    "r1_reasoning_kaggle_bundle.zip",
    "datamate_direct_coder_bundle.zip",
]

for repo_t in ["model", "dataset"]:
    for fname in filenames_to_upload:
        print(f"  -> Uploading to {TARGET_REPO} ({repo_t}): {fname}...")
        api.upload_file(
            path_or_fileobj=str(BUNDLE_ZIP),
            path_in_repo=fname,
            repo_id=TARGET_REPO,
            repo_type=repo_t,
            commit_message=f"Upload {fname} (T4 SDPA + Chunked Prefill 512 + Full Rulebook)",
        )
    for nb_name in [
        "Evaluate_Qwen25_14B_1M_Reasoning_Kaggle_2T4.ipynb",
        "Evaluate_Qwen25_14B_1M_Colab_G4.ipynb",
        "Train_Qwen25_14B_1M_Reasoning_Kaggle_2T4.ipynb",
    ]:
        nb_path = ROOT / "notebooks" / nb_name
        print(f"  -> Uploading notebook to {TARGET_REPO} ({repo_t}): notebooks/{nb_path.name}...")
        api.upload_file(
            path_or_fileobj=str(nb_path),
            path_in_repo=f"notebooks/{nb_path.name}",
            repo_id=TARGET_REPO,
            repo_type=repo_t,
            commit_message=f"Update {nb_path.name} (T4 SDPA + 512-token Chunked Prefill)",
        )

print("\n🔍 Verifying downloads from Hugging Face...")
for repo_t in ["model", "dataset"]:
    verified_path = hf_hub_download(
        repo_id=TARGET_REPO,
        filename="r1_reasoning_kaggle_bundle.zip",
        repo_type=repo_t,
        token=token,
    )
    print(f"  ✅ Verified {repo_t}: {verified_path}")

print("\n🎉 ALL UPLOADS AND VERIFICATIONS COMPLETED SUCCESSFULLY!")
