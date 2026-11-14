# Build a one-time bridge from a clean committed source snapshot.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (git status --porcelain) { throw 'Commit all source changes before building.' }
$version = (Get-Content -LiteralPath 'VERSION' -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$' -or $version -eq '0.9.0') { throw 'Bridge requires a new semantic version.' }
$revision = git rev-parse HEAD
$buildRoot = Join-Path $projectRoot ('build/update-bridge/' + [guid]::NewGuid().ToString('N'))
$cacheRoot = Join-Path $projectRoot 'build/tools'
New-Item -ItemType Directory -Path $buildRoot, $cacheRoot -Force | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-VerifiedPackage {
    param([string]$Name, [string]$Url, [string]$Sha256)
    $package = Join-Path $cacheRoot $Name
    if (-not (Test-Path -LiteralPath $package)) {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile ($package + '.part')
        if ((Get-FileHash -LiteralPath ($package + '.part') -Algorithm SHA256).Hash -ne $Sha256) {
            throw "SHA256 mismatch: $Name"
        }
        Move-Item -LiteralPath ($package + '.part') -Destination $package
    }
    if ((Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash -ne $Sha256) {
        throw "Cached package SHA256 mismatch: $Name"
    }
    return $package
}

$python = Get-VerifiedPackage 'python.3.13.15.nupkg' `
    'https://api.nuget.org/v3-flatcontainer/python/3.13.15/python.3.13.15.nupkg' `
    '05357887df50d3153efc681bdf432c321d3e2f9ce5788f99f4515b27e8fda0ac'
$compiler = Get-VerifiedPackage 'tools.innosetup.7.1.0.nupkg' `
    'https://api.nuget.org/v3-flatcontainer/tools.innosetup/7.1.0/tools.innosetup.7.1.0.nupkg' `
    'aad15c662593c6f5656457a5c001f4591babd72820cacf63f9706d4af5d93b75'
$payload = Join-Path $buildRoot 'payload'
$archive = Join-Path $buildRoot 'source.zip'
git archive --format=zip "--output=$archive" HEAD
if ($LASTEXITCODE -ne 0) { throw 'Could not export committed source.' }
[IO.Compression.ZipFile]::ExtractToDirectory($archive, $payload)
[IO.Compression.ZipFile]::ExtractToDirectory($python, (Join-Path $buildRoot 'python'))
[IO.Compression.ZipFile]::ExtractToDirectory($compiler, (Join-Path $buildRoot 'compiler'))
$runtime = Join-Path $payload 'runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $buildRoot 'python/tools') -Destination (Join-Path $runtime 'python') -Recurse
Push-Location -LiteralPath (Join-Path $payload 'updater')
try {
    $env:CGO_ENABLED = '0'
    $env:GOOS = 'windows'
    $env:GOARCH = 'amd64'
    go build -trimpath -buildvcs=false -o (Join-Path $payload 'Xuansi.exe') .
    if ($LASTEXITCODE -ne 0) { throw 'Launcher build failed.' }
} finally { Pop-Location }
@{ version = $version; commit = $revision; python = '3.13.15'; installer = 'Inno Setup 7.1.0'; go = (go version) } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $payload 'release.json') -Encoding UTF8
$iscc = Join-Path $buildRoot 'compiler/tools/ISCC.exe'
& $iscc '/Q' "/DAppVersion=$version" "/DPayload=$payload" "/DProjectRoot=$projectRoot" 'installer/update-bridge.iss'
if ($LASTEXITCODE -ne 0) { throw 'Bridge installer compilation failed.' }
$artifact = Join-Path $projectRoot "dist/Xuansi-$version-windows-x64-bridge.exe"
$hash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $([IO.Path]::GetFileName($artifact))" |
    Set-Content -LiteralPath (Join-Path $projectRoot 'dist/SHA256SUMS-bridge.txt') -Encoding ASCII
Write-Host "Built $artifact from $revision"
