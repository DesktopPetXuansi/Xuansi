# 从已提交的源码构建；只将 Git 跟踪文件和固定版本 Python 装入安装包。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (git status --porcelain) { throw 'Commit all source changes before building a release.' }
$version = (Get-Content -LiteralPath 'VERSION' -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'VERSION must use MAJOR.MINOR.PATCH.' }
$revision = git rev-parse HEAD
$buildRoot = Join-Path $projectRoot ('build/installer/' + [guid]::NewGuid().ToString('N'))
$cacheRoot = Join-Path $projectRoot 'build/tools'
New-Item -ItemType Directory -Path $buildRoot, $cacheRoot -Force | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-VerifiedPackage {
    param([string]$Name, [string]$Url, [string]$Sha256)
    $package = Join-Path $cacheRoot $Name
    if (-not (Test-Path -LiteralPath $package)) {
        Write-Host "Downloading $Name"
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile ($package + '.part')
        if ((Get-FileHash -LiteralPath ($package + '.part') -Algorithm SHA256).Hash -ne $Sha256) {
            throw "SHA256 mismatch: $Name"
        }
        Move-Item -LiteralPath ($package + '.part') -Destination $package
    }
    if ((Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash -ne $Sha256) {
        throw "Cached package SHA256 mismatch: $Name"
    }
    Write-Host "Verified $Name"
    return $package
}

$python = Get-VerifiedPackage 'python.3.13.15.nupkg' `
    'https://api.nuget.org/v3-flatcontainer/python/3.13.15/python.3.13.15.nupkg' `
    '05357887df50d3153efc681bdf432c321d3e2f9ce5788f99f4515b27e8fda0ac'
$compiler = Get-VerifiedPackage 'tools.innosetup.7.1.0.nupkg' `
    'https://api.nuget.org/v3-flatcontainer/tools.innosetup/7.1.0/tools.innosetup.7.1.0.nupkg' `
    'aad15c662593c6f5656457a5c001f4591babd72820cacf63f9706d4af5d93b75'
$payload = Join-Path $buildRoot 'payload'
$sourceZip = Join-Path $buildRoot 'source.zip'
git archive --format=zip "--output=$sourceZip" HEAD
if ($LASTEXITCODE -ne 0) { throw 'Could not export the committed source.' }
[System.IO.Compression.ZipFile]::ExtractToDirectory($sourceZip, $payload)
[System.IO.Compression.ZipFile]::ExtractToDirectory($python, (Join-Path $buildRoot 'python'))
[System.IO.Compression.ZipFile]::ExtractToDirectory($compiler, (Join-Path $buildRoot 'compiler'))
$runtime = Join-Path $payload 'runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $buildRoot 'python/tools') -Destination (Join-Path $runtime 'python') -Recurse
Copy-Item -LiteralPath (Join-Path $buildRoot 'compiler/tools/License.txt') -Destination (Join-Path $runtime 'INNO-LICENSE.txt')
# 记录安装包对应的源码，用户数据、开发环境与模型权重从未进入暂存树。
@{ version = $version; commit = $revision; python = '3.13.15'; installer = 'Inno Setup 7.1.0' } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $payload 'release.json') -Encoding UTF8
$iscc = Join-Path $buildRoot 'compiler/tools/ISCC.exe'
& $iscc '/Q' "/DAppVersion=$version" "/DPayload=$payload" "/DProjectRoot=$projectRoot" 'installer/online.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
$artifact = Join-Path $projectRoot "dist/Xuansi-$version-windows-x64-setup.exe"
$hash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $([IO.Path]::GetFileName($artifact))" |
    Set-Content -LiteralPath (Join-Path $projectRoot 'dist/SHA256SUMS.txt') -Encoding ASCII
Write-Host "Built $artifact"
Write-Host "Source commit: $revision"
Write-Host "SHA256: $hash"
