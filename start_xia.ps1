# XIA Windows 启动脚本
$ErrorActionPreference = "Continue"

$XIA_DIR = "E:\XIA"
$LOG_DIR = "$XIA_DIR\logs"
$DATA_DIR = "$XIA_DIR\data"

# 创建目录
New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
New-Item -ItemType Directory -Path $DATA_DIR -Force | Out-Null

# 检查是否已在运行
$existing = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*daemon*" }
if ($existing) {
    Write-Host "XIA daemon 已在运行"
    exit 0
}

# 启动 Ollama
$ollama = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host "启动 Ollama..."
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

# 启动 XIA daemon
Write-Host "启动 XIA daemon..."
Set-Location $XIA_DIR
$env:PYTHONIOENCODING = "utf-8"
$env:HF_HOME = "E:\huggingface_cache"

$proc = Start-Process python `
    -ArgumentList "-m","src.daemon.daemon" `
    -NoNewWindow `
    -PassThru `
    -RedirectStandardOutput "$LOG_DIR\daemon.log" `
    -RedirectStandardError "$LOG_DIR\daemon_error.log"

Start-Sleep -Seconds 3

if ($proc.HasExited) {
    Write-Host "启动失败，查看日志: $LOG_DIR\daemon_error.log"
    Get-Content "$LOG_DIR\daemon_error.log" -Tail 20
} else {
    Write-Host "XIA daemon 已启动 (PID=$($proc.Id))"
}
