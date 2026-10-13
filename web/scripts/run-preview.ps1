# 使用与生产镜像一致的 Next standalone 产物，静态文件复制仅限构建目录。
$ErrorActionPreference = 'Stop'
$taskFrontend = Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend'
$taskStandalone = Join-Path $taskFrontend '.next/standalone'
$taskEntry = Join-Path $taskStandalone 'server.js'
if (-not (Test-Path -LiteralPath $taskEntry)) { throw '先在 web/frontend 执行 pnpm build' }
foreach ($taskFolder in @('public', '.next/static')) {
    $taskDestination = Join-Path $taskStandalone $taskFolder
    New-Item -ItemType Directory -Path $taskDestination -Force | Out-Null
    Copy-Item -Path (Join-Path $taskFrontend "$taskFolder/*") -Destination $taskDestination -Recurse -Force
}
$env:HOSTNAME = '127.0.0.1'
$env:PORT = '3000'
$env:NODE_ENV = 'production'
$env:API_ORIGIN = 'http://127.0.0.1:8080'
$env:NEXT_TELEMETRY_DISABLED = '1'
Write-Host '启动玄司官网生产构建预览：http://localhost:3000'
node $taskEntry
if ($LASTEXITCODE -ne 0) { throw '生产构建预览退出' }
