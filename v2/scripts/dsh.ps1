param(
    [ValidateSet('Web', 'Headless')][string]$Mode = 'Web',
    [string]$Prompt = '',
    [string]$DshRoot = $(if ($env:V2_DSH_ROOT) { $env:V2_DSH_ROOT } else { 'D:\deepseek\deepseek-harness' }),
    [string]$BaseUrl = 'http://127.0.0.1:8012',
    [string]$ScopeId = 'local',
    [ValidateRange(1000, 300000)][int]$TimeoutMs = 60000,
    [string]$Model = 'deepseek-v4-flash',
    [string]$Provider = 'deepseek-official',
    [string]$CredentialsPath = $(Join-Path $env:USERPROFILE '.dsh\.credentials.yaml'),
    [ValidateRange(1, 65535)][int]$Port = 3081,
    [switch]$NoOpen,
    [switch]$DumpConfig
)

$ErrorActionPreference = 'Stop'
if ($Mode -eq 'Headless' -and -not $DumpConfig -and [string]::IsNullOrWhiteSpace($Prompt)) {
    throw 'Headless 模式需要 -Prompt，例如：-Prompt "研究601138的现金流风险，检索、读原文并保存带引用的报告。"'
}
$taskPrepareArgs = @{ DshRoot = $DshRoot; BaseUrl = $BaseUrl; ScopeId = $ScopeId; TimeoutMs = $TimeoutMs; Model = $Model; Provider = $Provider; PassThru = $true }
if ($PSBoundParameters.ContainsKey('CredentialsPath')) { $taskPrepareArgs.CredentialsPath = $CredentialsPath }
$taskInfo = & (Join-Path $PSScriptRoot 'prepare-dsh.ps1') @taskPrepareArgs
$taskPnpm = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
if (-not $taskPnpm) { throw '找不到 pnpm.cmd；请先安装 pnpm，或将现有 pnpm 目录加入 PATH。' }
if (-not $DumpConfig) {
    try { $taskHealth = Invoke-RestMethod -Uri "$($BaseUrl.TrimEnd('/'))/health" -TimeoutSec 5 }
    catch { throw '研究后端没有启动，请先在另一个终端运行 .\scripts\start.ps1。' }
    if ($taskHealth.stage -lt 3) { throw '后端尚未启用第三阶段接口，请初始化数据库并重启 .\scripts\start.ps1。' }
}
$taskPreviousHome = $env:DSH_HOME
$taskPreviousTelemetry = $env:DSH_TELEMETRY_DISABLED
Push-Location $taskInfo.DshRoot
try {
    $env:DSH_HOME = $taskInfo.Home
    $env:DSH_TELEMETRY_DISABLED = '1'
    $taskProfile = $Mode.ToLowerInvariant()
    $taskPatch = if ($Mode -eq 'Web') { $taskInfo.WebPatch } else { $taskInfo.HeadlessPatch }
    $taskArguments = @('dsh', '--profile', $taskProfile, '--patch', $taskPatch)
    if ($DumpConfig) { $taskArguments += '--dump-config' }
    elseif ($Mode -eq 'Headless') { $taskArguments += $Prompt }
    else {
        $taskArguments += @('--port', [string]$Port)
        if ($NoOpen) { $taskArguments += '--no-open' }
    }
    & $taskPnpm.Source @taskArguments
    if ($LASTEXITCODE -ne 0) { throw "dsh 退出码 $LASTEXITCODE；请按上方的实际错误排查。" }
} finally {
    $env:DSH_HOME = $taskPreviousHome
    $env:DSH_TELEMETRY_DISABLED = $taskPreviousTelemetry
    Pop-Location
}
