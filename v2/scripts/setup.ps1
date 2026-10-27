param([string]$PythonPath = "", [switch]$SkipDatabase)
$ErrorActionPreference = "Stop"
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskVenv = Join-Path $taskRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $taskVenv)) {
    if ($PythonPath) {
        & $PythonPath -m venv (Join-Path $taskRoot ".venv")
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv (Join-Path $taskRoot ".venv")
    } else {
        & python -m venv (Join-Path $taskRoot ".venv")
    }
    if ($LASTEXITCODE -ne 0) { throw "Python 环境创建失败，需要 Python 3.11+。" }
}

$taskEnv = Join-Path $taskRoot ".env"
if (-not (Test-Path -LiteralPath $taskEnv)) {
    $taskPassword = [Guid]::NewGuid().ToString("N")
    @(
        "V2_DB_PORT=55432"
        "V2_API_PORT=8012"
        "V2_DB_PASSWORD=$taskPassword"
        "V2_DATABASE_URL=postgresql://trader:${taskPassword}@127.0.0.1:55432/trader_v2"
    ) | Set-Content -LiteralPath $taskEnv -Encoding UTF8
}

Push-Location $taskRoot
try {
    $taskPythonTag = & $taskVenv -c "import sys; print('cp' + str(sys.version_info.major) + str(sys.version_info.minor))"
    $taskCpuWheel = Join-Path $taskRoot ".runtime\wheels\torch-2.7.1+cpu-${taskPythonTag}-${taskPythonTag}-win_amd64.whl"
    if (Test-Path -LiteralPath $taskCpuWheel) {
        & $taskVenv -m pip install $taskCpuWheel --disable-pip-version-check
    } else {
        & $taskVenv -m pip install "torch==2.7.1" --index-url https://download.pytorch.org/whl/cpu --disable-pip-version-check
    }
    if ($LASTEXITCODE -ne 0) { throw "CPU Embedding 运行依赖安装失败。" }
    & $taskVenv -m pip install -e ".[dev]" -c requirements.lock --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw "依赖安装失败。" }
    if (-not $SkipDatabase) {
        & (Join-Path $PSScriptRoot "database.ps1") -Action Start
        & $taskVenv -m trader_v2.cli init-db
        if ($LASTEXITCODE -ne 0) { throw "数据库初始化失败。" }
    }
} finally {
    Pop-Location
}
Write-Host "准备完成。运行 .\scripts\start.ps1 启动服务。第二阶段先运行 python -m trader_v2.cli prepare-model，再运行 .\scripts\vector-demo.ps1。"
