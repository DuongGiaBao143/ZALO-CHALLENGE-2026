param(
    [string]$Notebook = 'crinkk/02-train-sft-qwen7b-kaggle-2t4-208'
)

$ErrorActionPreference = 'Stop'
if (-not (Get-Command kaggle -ErrorAction SilentlyContinue)) {
    throw 'Install the Kaggle CLI first: python -m pip install -U kaggle'
}
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskOutput = Join-Path $taskRoot 'result/kaggle_live_monitor'
New-Item -ItemType Directory -Force -Path $taskOutput | Out-Null
$taskLogPath = Join-Path $taskOutput 'train-live.log'
Write-Host "Streaming $Notebook; log: $taskLogPath"
& kaggle kernels logs $Notebook --follow 2>&1 | Tee-Object -FilePath $taskLogPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "Kaggle log stream exited with code $LASTEXITCODE"
}
& kaggle kernels status $Notebook
