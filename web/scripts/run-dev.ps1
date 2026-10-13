# Go 是唯一业务后端；本脚本为独立终端加载项目配置并运行所选服务。
param([Parameter(Mandatory)][ValidateSet('api','worker','frontend')][string]$Service)
$ErrorActionPreference='Stop'
$taskWebRoot=Split-Path -Parent $PSScriptRoot
$taskEnvFile=Join-Path $taskWebRoot '.env'
if (Test-Path -LiteralPath $taskEnvFile) {
    foreach ($taskLine in [System.IO.File]::ReadAllLines($taskEnvFile)) {
        $taskValue=$taskLine.Trim()
        if (-not $taskValue -or $taskValue.StartsWith('#')) { continue }
        $taskSplit=$taskValue.IndexOf('=')
        if ($taskSplit -lt 1) { throw '开发环境文件必须使用 KEY=VALUE 格式' }
        $taskKey=$taskValue.Substring(0,$taskSplit).Trim()
        if ($taskKey -notmatch '^[A-Z][A-Z0-9_]+$' -or $taskKey -in @('HOME','CODEX_HOME','PATH')) { throw '开发环境变量名称无效' }
        $taskContent=$taskValue.Substring($taskSplit+1).Trim().Trim('"').Trim("'")
        [Environment]::SetEnvironmentVariable($taskKey,$taskContent,'Process')
    }
}
$taskDefaults=@{
    DATABASE_URL='postgres://xuansi@127.0.0.1:54329/xuansi?sslmode=disable'
    APP_ENV='development'; APP_URL='http://localhost:3000'; HTTP_ADDRESS='127.0.0.1:8080'
    API_ORIGIN='http://127.0.0.1:8080'; STORAGE_DRIVER='local'
    STORAGE_PATH=(Join-Path $taskWebRoot '.data/storage')
    SMTP_HOST='127.0.0.1'; SMTP_PORT='1025'; SMTP_FROM='noreply@localhost'
    TRUSTED_PROXY_CIDRS='127.0.0.1/32,::1/128'; NEXT_TELEMETRY_DISABLED='1'
}
foreach ($taskKey in $taskDefaults.Keys) {
    if (-not [Environment]::GetEnvironmentVariable($taskKey,'Process')) {
        [Environment]::SetEnvironmentVariable($taskKey,$taskDefaults[$taskKey],'Process')
    }
}
Write-Host "启动玄司官网开发服务：$Service"
if ($Service -eq 'frontend') {
    Set-Location -LiteralPath (Join-Path $taskWebRoot 'frontend')
    pnpm dev
} else {
    Set-Location -LiteralPath (Join-Path $taskWebRoot 'backend')
    if ($Service -eq 'api') { go run ./cmd/api -migrate } else { go run ./cmd/worker }
}
if ($LASTEXITCODE -ne 0) { throw "开发服务退出：$Service" }
