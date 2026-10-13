# OpenAPI 是可编辑契约源；工具版本固定，生成文件不手动修改。
$ErrorActionPreference='Stop'
$taskWebRoot=Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath (Join-Path $taskWebRoot 'backend')
try {
    go run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@v2.8.0 -generate types -package apicontract -o ../contracts/generated/api.go ../contracts/openapi.yaml
    if ($LASTEXITCODE -ne 0) { throw 'Go契约生成失败' }
} finally { Pop-Location }
Push-Location -LiteralPath (Join-Path $taskWebRoot 'frontend')
try {
    pnpm dlx openapi-typescript@7.13.0 ../contracts/openapi.yaml -o ../contracts/generated/api.d.ts
    if ($LASTEXITCODE -ne 0) { throw 'TypeScript契约生成失败' }
} finally { Pop-Location }
Write-Host 'Go 与 TypeScript 契约生成完成'
