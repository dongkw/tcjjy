param([ValidateSet("Start", "Stop", "Status")][string]$Action = "Start")
$ErrorActionPreference = "Stop"
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskInstallLocation = (Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Docker Desktop" -ErrorAction SilentlyContinue).InstallLocation
$taskInstallCandidates = @(
    $taskInstallLocation
    "D:\Docker"
    (Join-Path $env:ProgramFiles "Docker\Docker")
) | Where-Object { $_ } | Select-Object -Unique
$taskPlugin = $null
$taskCli = $null
foreach ($taskInstall in $taskInstallCandidates) {
    $taskCandidatePlugin = Join-Path $taskInstall "resources\cli-plugins\docker-compose.exe"
    $taskCandidateCli = Join-Path $taskInstall "resources\bin\docker.exe"
    if ((Test-Path -LiteralPath $taskCandidatePlugin -PathType Leaf) -and
        (Test-Path -LiteralPath $taskCandidateCli -PathType Leaf)) {
        $taskPlugin = $taskCandidatePlugin
        $taskCli = $taskCandidateCli
        break
    }
}
$taskArguments = @("--env-file", (Join-Path $taskRoot ".env"), "-f", (Join-Path $taskRoot "compose.yaml"))
switch ($Action) {
    "Start" { $taskArguments += @("up", "-d", "--wait", "db") }
    "Stop" { $taskArguments += @("stop", "db") }
    "Status" { $taskArguments += @("ps") }
}
$taskOriginalPath = $env:Path
try {
    if ($taskPlugin) {
        # Compose must resolve docker.exe from the same installation, even when
        # this PowerShell still has the removed C: installation in PATH.
        $env:Path = (Split-Path -Parent $taskCli) + ";" + $taskOriginalPath
        & $taskPlugin @taskArguments
    } else {
        & docker compose @taskArguments
    }
    if ($LASTEXITCODE -ne 0) { throw "数据库操作失败，请确认 Docker Desktop 已运行。" }
} finally {
    $env:Path = $taskOriginalPath
}
