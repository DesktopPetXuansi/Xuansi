# 创建本项目和当前用户桌面的启动入口，已有其他目标的同名文件不会被覆盖。
$ErrorActionPreference = 'Stop'
$petRoot = Split-Path -Parent $PSScriptRoot
$petPython = Join-Path $petRoot '.venv/Scripts/pythonw.exe'
if (-not (Test-Path -LiteralPath $petPython)) { throw 'Run setup.ps1 first.' }
$petShell = New-Object -ComObject WScript.Shell
$petDesktop = [Environment]::GetFolderPath('Desktop')
foreach ($petShortcutPath in @((Join-Path $petRoot '启动桌宠.lnk'), (Join-Path $petDesktop '玄司 AI 桌宠.lnk'))) {
    $petShortcut = $petShell.CreateShortcut($petShortcutPath)
    if ((Test-Path -LiteralPath $petShortcutPath) -and $petShortcut.TargetPath -ne $petPython) {
        throw 'A shortcut with a different target already exists.'
    }
    $petShortcut.TargetPath = $petPython
    $petShortcut.Arguments = '-m pet'
    $petShortcut.WorkingDirectory = $petRoot
    $petShortcut.IconLocation = (Join-Path $petRoot 'assets/xuansi/icon.ico')
    $petShortcut.Description = 'Xuansi local AI companion: click to open settings.'
    # pythonw 本身没有控制台；保留 GUI 正常显示，由 Qt 控制不抢焦点。
    $petShortcut.WindowStyle = 1
    $petShortcut.Save()
}
# 新入口成功后，仅移除确认指向本项目的旧名称快捷方式。
$petOldShortcut = Join-Path $petDesktop '糯米 AI 桌宠.lnk'
if (Test-Path -LiteralPath $petOldShortcut) {
    $petOld = $petShell.CreateShortcut($petOldShortcut)
    if ($petOld.TargetPath -eq $petPython -and $petOld.Arguments -eq '-m pet') {
        Remove-Item -LiteralPath $petOldShortcut
    }
}
Write-Host 'Local and desktop shortcuts created.'
