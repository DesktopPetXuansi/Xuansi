package backend

import "embed"

// Migrations 随二进制发布，工作目录变化不影响迁移。
//
//go:embed migrations/*.sql
var Migrations embed.FS
