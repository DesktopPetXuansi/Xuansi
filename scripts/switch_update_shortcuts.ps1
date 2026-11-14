param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$Version
)

$ErrorActionPreference = 'Stop'
$rootPath = [IO.Path]::GetFullPath($Root)
$launcher = Join-Path $rootPath 'Xuansi.exe'
$legacy = Join-Path $rootPath '.venv\Scripts\pythonw.exe'
$icon = Join-Path $rootPath "versions\$Version\assets\xuansi\icon.ico"
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf) -or
    -not (Test-Path -LiteralPath $icon -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $rootPath 'update\update-state.json') -PathType Leaf)) {
    throw '更新启动器尚未完成健康确认。'
}
$shell = New-Object -ComObject WScript.Shell
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) '玄司 AI 桌宠\玄司 AI 桌宠.lnk'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcuts = @($startMenu,
    (Join-Path $desktop '玄司 AI 桌宠（安装版）.lnk'),
    (Join-Path $desktop '玄司 AI 桌宠.lnk'),
    (Join-Path $rootPath '启动桌宠.lnk'))
$backups = @()
try {
    foreach ($path in $shortcuts) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -and $path -ne $startMenu) { continue }
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $existing = $shell.CreateShortcut($path)
            if ($existing.TargetPath -ine $legacy -and $existing.TargetPath -ine $launcher) {
                if ($path -eq $startMenu) { throw "开始菜单入口目标与本项目不符：$path" }
                continue
            }
            $backup = "$path.update-backup-$([guid]::NewGuid().ToString('N'))"
            Copy-Item -LiteralPath $path -Destination $backup
            $backups += [pscustomobject]@{Path=$path; Backup=$backup}
        } else {
            New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
        }
        $shortcut = $shell.CreateShortcut($path)
        $shortcut.TargetPath = $launcher
        $shortcut.Arguments = ''
        $shortcut.WorkingDirectory = $rootPath
        $shortcut.IconLocation = $icon
        $shortcut.Description = '玄司 AI 桌宠'
        $shortcut.Save()
    }
} catch {
    foreach ($entry in $backups) {
        Copy-Item -LiteralPath $entry.Backup -Destination $entry.Path -Force
    }
    throw
} finally {
    foreach ($entry in $backups) {
        Remove-Item -LiteralPath $entry.Backup -ErrorAction SilentlyContinue
    }
}
