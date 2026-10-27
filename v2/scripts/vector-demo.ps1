param([ValidateRange(1,20)][int]$TopK = 5, [double]$MinScore = 0.55)
$ErrorActionPreference = "Stop"
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $taskPython)) { throw "请先运行 .\scripts\setup.ps1。" }
if ([double]::IsNaN($MinScore) -or [double]::IsInfinity($MinScore) -or $MinScore -lt 0 -or $MinScore -gt 1) {
    throw "MinScore 必须是0～1的有限数字。"
}
Push-Location $taskRoot
try {
    & $taskPython -m trader_v2.cli init-db
    if ($LASTEXITCODE -ne 0) { throw "数据库初始化失败。" }
    & $taskPython -m trader_v2.cli knowledge-demo
    if ($LASTEXITCODE -ne 0) { throw "学习资料入库失败；模型需先通过 prepare-model 单独准备。" }
    & $taskPython -m trader_v2.cli evaluate-retrieval --top-k $TopK --min-score $MinScore
    if ($LASTEXITCODE -ne 0) { throw "检索评测存在未通过项，详细报告已经输出；若评测完成则报告也已入库。" }
} finally { Pop-Location }
