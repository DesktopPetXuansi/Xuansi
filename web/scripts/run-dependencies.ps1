# Docker 是常规入口；便携模式复用当前工作区已准备的官方本机工具。
param([switch]$Portable, [ValidateRange(1,65535)][int]$PostgresPort = 54329)
$ErrorActionPreference = 'Stop'
$taskWebRoot = Split-Path -Parent $PSScriptRoot
if (-not $Portable) {
    Push-Location -LiteralPath $taskWebRoot
    try {
        docker compose up -d db mail
        if ($LASTEXITCODE -ne 0) { throw '数据库或开发邮件容器启动失败' }
    } finally { Pop-Location }
    exit 0
}

$taskRuntime = Join-Path $taskWebRoot '.runtime'
$taskPgBin = Join-Path $taskRuntime 'tools/postgresql/pgsql/bin'
$taskMail = Join-Path $taskRuntime 'tools/mailpit/mailpit.exe'
$taskPgData = Join-Path $taskRuntime 'postgres'
if (-not (Test-Path -LiteralPath (Join-Path $taskPgBin 'pg_ctl.exe')) -or -not (Test-Path -LiteralPath $taskMail)) {
    throw '缺少便携官方工具，参照 web/README.md 的依赖目录说明；也可使用常规 Docker 模式'
}
if (-not (Test-Path -LiteralPath (Join-Path $taskPgData 'PG_VERSION'))) {
    & (Join-Path $taskPgBin 'initdb.exe') -D $taskPgData -U xuansi -A trust -E UTF8 --locale=C
    if ($LASTEXITCODE -ne 0) { throw '本机开发数据库初始化失败' }
}
& (Join-Path $taskPgBin 'pg_ctl.exe') -D $taskPgData status *> $null
if ($LASTEXITCODE -ne 0) {
    & (Join-Path $taskPgBin 'pg_ctl.exe') -D $taskPgData -l (Join-Path $taskRuntime 'postgres.log') -o "-h 127.0.0.1 -p $PostgresPort" -w start
    if ($LASTEXITCODE -ne 0) { throw '本机开发数据库启动失败，请检查忽略目录中的 postgres.log' }
}
foreach ($taskDatabase in @('xuansi', 'xuansi_test')) {
    $taskExists = & (Join-Path $taskPgBin 'psql.exe') -h 127.0.0.1 -p $PostgresPort -U xuansi -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$taskDatabase'"
    if ($LASTEXITCODE -ne 0) { throw '本机数据库连接失败' }
    if ($taskExists -ne '1') {
        & (Join-Path $taskPgBin 'createdb.exe') -h 127.0.0.1 -p $PostgresPort -U xuansi $taskDatabase
        if ($LASTEXITCODE -ne 0) { throw '开发数据库创建失败' }
    }
}
$taskListener = Get-NetTCPConnection -State Listen -LocalPort 8025 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($taskListener) {
    $taskOwner = Get-Process -Id $taskListener.OwningProcess
    if ($taskOwner.Path -ne $taskMail) { throw '8025 端口被其他服务占用，未操作该服务' }
} else {
    $taskArguments = @('--listen', '127.0.0.1:8025', '--smtp', '127.0.0.1:1025', '--database', (Join-Path $taskRuntime 'mailpit.sqlite3'), '--disable-version-check', '--smtp-disable-rdns', '--max-age', '1d', '--quiet')
    Start-Process -FilePath $taskMail -ArgumentList $taskArguments -WindowStyle Hidden
}
Write-Host '本机 PostgreSQL 与开发邮件已就绪；邮箱捕获界面：http://127.0.0.1:8025'
