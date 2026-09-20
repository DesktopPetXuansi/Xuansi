# 安装仅影响本项目虚拟环境和指定的 D 盘模型目录，不设置开机启动。
param(
    [string]$PythonPath = '',
    [switch]$SkipShortcuts
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Path 'data' -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $PSScriptRoot 'data/setup.log') -Append | Out-Null
try {
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        if (-not $PythonPath -and (Test-Path -LiteralPath 'runtime/python/python.exe')) {
            $PythonPath = Join-Path $PSScriptRoot 'runtime/python/python.exe'
        }
        Write-Host 'Creating the private Python environment...'
        if ($PythonPath) {
            & $PythonPath -m venv .venv
        } else {
            py -3.13 -m venv .venv
        }
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 is required.' }
    }
    & '.venv/Scripts/python.exe' -c 'import sys, struct; sys.exit(0 if sys.version_info[:2] == (3, 13) and struct.calcsize(chr(80)) == 8 else 1)'
    if ($LASTEXITCODE -ne 0) { throw '64-bit Python 3.13 is required.' }
    Write-Host 'Installing dependencies, then downloading and verifying models. This may take a while.'
    & '.venv/Scripts/python.exe' -m pip install --disable-pip-version-check -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & '.venv/Scripts/python.exe' -X utf8 scripts/download_assets.py
    if ($LASTEXITCODE -ne 0) { throw 'Model verification failed.' }
    & '.venv/Scripts/python.exe' -X utf8 scripts/download_realtime.py
    if ($LASTEXITCODE -ne 0) { throw 'Realtime model verification failed.' }
    # 打包版的快捷方式交由安装器管理，避免覆盖源码版入口。
    if (-not $SkipShortcuts) { & './scripts/create_shortcuts.ps1' }
    Write-Host 'Setup completed successfully.'
} finally {
    Stop-Transcript | Out-Null
}
