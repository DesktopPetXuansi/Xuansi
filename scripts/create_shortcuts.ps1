# 创建本项目和当前用户桌面的启动入口，已有其他目标的同名文件不会被覆盖。
$ErrorActionPreference = 'Stop'
$petRoot = Split-Path -Parent $PSScriptRoot
$petPython = Join-Path $petRoot '.venv/Scripts/pythonw.exe'
if (-not (Test-Path -LiteralPath $petPython)) { throw 'Run setup.ps1 first.' }
$petShell = New-Object -ComObject WScript.Shell
$petDesktop = [Environment]::GetFolderPath('Desktop')
foreach ($petShortcutPath in @((Join-Path $petRoot '启动桌宠.lnk'), (Join-Path $petDesktop '糯米 AI 桌宠.lnk'))) {
    $petShortcut = $petShell.CreateShortcut($petShortcutPath)
    if ((Test-Path -LiteralPath $petShortcutPath) -and $petShortcut.TargetPath -ne $petPython) {
        throw 'A shortcut with a different target already exists.'
    }
    $petShortcut.TargetPath = $petPython
    $petShortcut.Arguments = '-m pet'
    $petShortcut.WorkingDirectory = $petRoot
    $petShortcut.IconLocation = (Join-Path $petRoot 'assets/neko/sprites/ico/Awake.ico')
    $petShortcut.Description = 'Local AI companion: click the cat to open settings.'
    # pythonw 本身没有控制台；保留 GUI 正常显示，由 Qt 控制不抢焦点。
    $petShortcut.WindowStyle = 1
    $petShortcut.Save()
}
Write-Host 'Local and desktop shortcuts created.'
