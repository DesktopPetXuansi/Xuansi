# 安装仅影响本项目虚拟环境和指定的 D 盘模型目录，不设置开机启动。
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    py -3.13 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 is required.' }
}
& '.venv/Scripts/python.exe' -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& '.venv/Scripts/python.exe' -X utf8 scripts/download_assets.py
if ($LASTEXITCODE -ne 0) { throw 'Model verification failed.' }
& './scripts/create_shortcuts.ps1'
Write-Host 'Ready. Double-click the desktop shortcut or the VBS launcher.'
