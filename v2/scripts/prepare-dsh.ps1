param(
    [string]$DshRoot = $(if ($env:V2_DSH_ROOT) { $env:V2_DSH_ROOT } else { 'D:\deepseek\deepseek-harness' }),
    [string]$BaseUrl = 'http://127.0.0.1:8012',
    [string]$ScopeId = 'local',
    [ValidateRange(1000, 300000)][int]$TimeoutMs = 60000,
    [string]$Model = 'deepseek-v4-flash',
    [string]$Provider = 'deepseek-official',
    [string]$CredentialsPath = $(Join-Path $env:USERPROFILE '.dsh\.credentials.yaml'),
    [switch]$PassThru
)

$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskDshRoot = [IO.Path]::GetFullPath($DshRoot)
$taskPluginRoot = Join-Path $taskRoot 'dsh-plugin'
$taskPluginEntry = Join-Path $taskPluginRoot 'src\index.mjs'
$taskRuntime = Join-Path $taskRoot '.runtime\dsh'
$taskHome = Join-Path $taskRoot '.runtime\dsh-home'
$taskPresets = Join-Path $taskRuntime 'presets'
$taskPreset = Join-Path $taskPresets 'trader-research'

function ConvertTo-TaskYamlString([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

function Assert-TaskFile([string]$Path, [string]$Help) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Help 缺少：$Path" }
}

Assert-TaskFile (Join-Path $taskDshRoot 'apps\cli\src\bin.ts') '请用 -DshRoot 指定已有的 dsh 源码目录。'
Assert-TaskFile (Join-Path $taskDshRoot 'node_modules\tsx\dist\loader.mjs') 'dsh 尚未安装依赖，请先在其源码目录执行 pnpm install。'
Assert-TaskFile (Join-Path $taskDshRoot 'packages\core\tools\lib\index.js') 'dsh 尚未构建，请先在其源码目录执行 pnpm run build。'
Assert-TaskFile $taskPluginEntry 'V2 的 dsh 插件入口不存在。'
if ($ScopeId -notmatch '^[A-Za-z0-9_.:-]{1,80}$') { throw 'ScopeId 只能包含字母、数字、下划线、点、冒号和横线，长度1～80。' }
if ([string]::IsNullOrWhiteSpace($Model) -or [string]::IsNullOrWhiteSpace($Provider)) { throw 'Model 和 Provider 不能为空。' }
$taskUri = [uri]$BaseUrl
if (-not $taskUri.IsAbsoluteUri -or $taskUri.Scheme -ne 'http' -or
    $taskUri.Host -notin @('127.0.0.1', 'localhost', '[::1]', '::1') -or
    $taskUri.UserInfo -or $taskUri.Query -or $taskUri.Fragment -or
    $taskUri.AbsolutePath -ne '/') { throw 'BaseUrl 必须是本机 HTTP origin，例如 http://127.0.0.1:8012。' }

New-Item -ItemType Directory -Path $taskRuntime, $taskHome, $taskPreset -Force | Out-Null
$taskModules = Join-Path $taskPluginRoot 'node_modules\@deepseek-ai'
New-Item -ItemType Directory -Path $taskModules -Force | Out-Null
# Junctions live only in V2; dependencies resolve against the same dsh build as the launcher.
$taskPeers = @{
    'dsh-tools' = Join-Path $taskDshRoot 'packages\core\tools'
    'schemastery' = Join-Path $taskDshRoot 'vendor\schemastery'
}
foreach ($taskPeer in $taskPeers.GetEnumerator()) {
    $taskLink = Join-Path $taskModules $taskPeer.Key
    $taskTarget = [IO.Path]::GetFullPath($taskPeer.Value)
    Assert-TaskFile (Join-Path $taskTarget 'package.json') 'dsh 依赖目录不完整。'
    if (Test-Path -LiteralPath $taskLink) {
        $taskExisting = Get-Item -LiteralPath $taskLink -Force
        if ($taskExisting.LinkType -ne 'Junction' -or [IO.Path]::GetFullPath([string]$taskExisting.Target) -ne $taskTarget) {
            throw "现有插件依赖与 -DshRoot 不匹配：$taskLink。请使用原源码路径，或检查这个链接后再调整。"
        }
    } else {
        New-Item -ItemType Junction -Path $taskLink -Target $taskTarget | Out-Null
    }
}

$taskPluginYaml = ConvertTo-TaskYamlString ($taskPluginEntry.Replace('\', '/'))
$taskBaseYaml = ConvertTo-TaskYamlString $BaseUrl.TrimEnd('/')
$taskScopeYaml = ConvertTo-TaskYamlString $ScopeId
$taskPresetYaml = @"
- id: trader-research-tools
  name: $taskPluginYaml
  config:
    baseUrl: $taskBaseYaml
    scopeId: $taskScopeYaml
    timeoutMs: $TimeoutMs
"@
Set-Content -LiteralPath (Join-Path $taskPreset 'agent.cordis.yml') -Value $taskPresetYaml -Encoding utf8
Set-Content -LiteralPath (Join-Path $taskPreset 'preset.yml') -Value "name: '天才交易员·研究学习'`ndescription: '研究资料、原文引用和长期记忆的 Agent 学习演示。'`norder: 0" -Encoding utf8

$taskCommonRows = @"
- id: system-prompt
  config:
    personaPrefix: ''
    personaSuffix: ''
- id: agent-default-model
  config:
    provider: $(ConvertTo-TaskYamlString $Provider)
    model: $(ConvertTo-TaskYamlString $Model)
"@
# The research preset exposes only this project's tools. These host registrations are disabled in both surfaces.
$taskDisabled = @('tool-bash', 'tool-pwsh', 'tool-jobs', 'tool-fs', 'tool-fs-search', 'tool-skill', 'tool-subagent-control', 'tool-subagent-list-agents', 'tool-subagent', 'tool-subagent-fork', 'tool-workflow', 'tool-todo', 'tool-goal', 'tool-ralph', 'tool-web', 'agent-instructions', 'plan-mode', 'command-goal', 'goal-round-driver', 'compaction-basic', 'command-compact', 'tool-result-pruner')
foreach ($taskRow in $taskDisabled) { $taskCommonRows += "`n- id: $taskRow`n  disabled: true`n" }
if ($CredentialsPath -and (Test-Path -LiteralPath $CredentialsPath -PathType Leaf)) {
    $taskCredentialYaml = ConvertTo-TaskYamlString ([IO.Path]::GetFullPath($CredentialsPath).Replace('\', '/'))
    $taskCommonRows += "`n- id: credentials`n  config:`n    path: $taskCredentialYaml`n    watch: false`n"
} elseif ($CredentialsPath -and $PSBoundParameters.ContainsKey('CredentialsPath')) {
    throw "指定的凭据文件不存在：$CredentialsPath"
}
$taskRootsYaml = ConvertTo-TaskYamlString ($taskPresets.Replace('\', '/'))
$taskRosterConfig = @"
    default: trader-research
    includeShippedRoot: false
    includeUserRoot: false
    roots:
      - path: $taskRootsYaml
        trust: system
"@
$taskWebPatch = "$taskCommonRows`n- id: agent-presets`n  config:`n$taskRosterConfig"
$taskHeadlessPatch = @"
$taskCommonRows
- insert:
    - id: trader-research-tools
      name: $taskPluginYaml
      config:
        baseUrl: $taskBaseYaml
        scopeId: $taskScopeYaml
        timeoutMs: $TimeoutMs
"@
$taskWebPath = Join-Path $taskRuntime 'web.patch.yml'
$taskHeadlessPath = Join-Path $taskRuntime 'headless.patch.yml'
Set-Content -LiteralPath $taskWebPath -Value $taskWebPatch -Encoding utf8
Set-Content -LiteralPath $taskHeadlessPath -Value $taskHeadlessPatch -Encoding utf8
$taskInfo = [pscustomobject]@{ DshRoot = $taskDshRoot; Home = $taskHome; WebPatch = $taskWebPath; HeadlessPatch = $taskHeadlessPath; Preset = $taskPreset }
if ($PassThru) { return $taskInfo }
Write-Host "dsh 研究插件已准备：$taskPreset"
Write-Host "运行 Web：.\scripts\dsh.ps1"
Write-Host '运行一次任务：.\scripts\dsh.ps1 -Mode Headless -Prompt "研究601138的现金流风险，检索、读原文并保存带引用的报告。"'
