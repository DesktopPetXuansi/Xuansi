param(
    [string]$EditorDirectory = 'E:\app\Live2D Cubism 5.3'
)

$ErrorActionPreference = 'Stop'
$assetDirectory = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$projectDirectory = (Resolve-Path -LiteralPath (Join-Path $assetDirectory '..\..')).Path
$buildDirectory = Join-Path $projectDirectory 'data\verification\stickman-build'
$libraryDirectory = Join-Path $EditorDirectory 'app\lib'
$classpath = "$buildDirectory;$libraryDirectory\*;$libraryDirectory\jogl\*"
New-Item -ItemType Directory -Path $buildDirectory -Force | Out-Null

# 固定内存上限，避免编辑器默认的大内存配置影响桌面其他程序。
Write-Host '[火柴人] 编译模型制作脚本'
& javac '-J-Xmx256m' '-proc:none' '-encoding' 'UTF-8' '-classpath' $classpath '-d' $buildDirectory (Join-Path $PSScriptRoot 'BuildModel.java')
if ($LASTEXITCODE -ne 0) { throw '模型制作脚本编译失败' }

Push-Location -LiteralPath $EditorDirectory
try {
    Write-Host '[火柴人] 生成可编辑工程与运行时模型'
    & java '-Xms64m' '-Xmx512m' '-Dfile.encoding=UTF-8' "-Djava.library.path=$EditorDirectory\app\dll64;$EditorDirectory\app\dll64\windows-amd64" '-classpath' $classpath 'com.desktopaipet.stickman.BuildModel' $assetDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Live2D 模型制作失败，详见上方错误' }
} finally {
    Pop-Location
}
