param([string]$Symbol = "601138", [ValidateSet("fixture", "live")][string]$Mode = "fixture")
$ErrorActionPreference = "Stop"
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $taskPython)) { throw "请先运行 .\scripts\setup.ps1。" }
Push-Location $taskRoot
try {
    & $taskPython -m trader_v2.cli analyze $Symbol --mode $Mode --limit 120
    if ($LASTEXITCODE -ne 0) { throw "数据分析失败。" }
} finally { Pop-Location }
