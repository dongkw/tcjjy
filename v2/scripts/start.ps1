param([int]$Port = 0)
$ErrorActionPreference = "Stop"
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $taskPython)) { throw "请先运行 .\scripts\setup.ps1。" }
Push-Location $taskRoot
try {
    if ($Port -gt 0) { & $taskPython -m trader_v2.cli serve --port $Port }
    else { & $taskPython -m trader_v2.cli serve }
    if ($LASTEXITCODE -ne 0) { throw "服务启动失败。" }
} finally { Pop-Location }
