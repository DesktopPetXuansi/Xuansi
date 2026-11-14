# 操作手册

2026-11-12 基础文档任务仅核对下列步骤的来源和入口，命令均未执行。执行前确认当前任务的授权及目标环境。

## 桌面客户端开发

1. 在项目根目录按 [README 的源码运行步骤](../../README.md#从源码运行)准备 Windows 和 64 位 Python 3.13 环境。首次安装前按[安装须知](../../installer/安装须知.txt)核对网络、磁盘与运行条件。
2. 使用项目虚拟环境，按 [pytest 和 Ruff 配置](../../pyproject.toml)选择检查范围。下列为已记录的全量测试和桌面代码检查命令。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check pet tests scripts
```

3. 安装包验证另行核对包内版本及来源，按任务实际验证安装、启动、升级或卸载。安装器定义和随包文档见[安装与部署映射](MAP.md#安装与部署)。公开下载、实际安装和用户验收分别记录证据。

## 官网本地运行

以下命令从[玄司官网私有仓库](https://github.com/DesktopPetXuansi/xuansi_Web)的根目录运行。

1. 按[前端声明](https://github.com/DesktopPetXuansi/xuansi_Web/blob/main/web/frontend/package.json)和[后端工具链](https://github.com/DesktopPetXuansi/xuansi_Web/blob/main/web/backend/go.mod)准备环境。首次创建 `web/.env` 时参考[本地示例](https://github.com/DesktopPetXuansi/xuansi_Web/blob/main/web/.env.example)，保留已有配置。

   首次准备前端时，在 `web/frontend` 中运行 `pnpm install --frozen-lockfile`。

2. 在项目根目录使用 Docker 启动数据库和本地邮件捕获依赖。脚本入口见[依赖启动](https://github.com/DesktopPetXuansi/xuansi_Web/blob/main/web/scripts/run-dependencies.ps1)。

```powershell
& web/scripts/run-dependencies.ps1
```

   Windows 可按[官网仓库的便携依赖说明](https://github.com/DesktopPetXuansi/xuansi_Web#本地运行)使用 `-Portable`，复用官网工作区的 PostgreSQL、存储与本地邮件捕获数据。

3. 使用三个独立终端，先启动 API，确认其 `/readyz` 就绪，再启动 worker 和前端。入口见[本地开发脚本](https://github.com/DesktopPetXuansi/xuansi_Web/blob/main/web/scripts/run-dev.ps1)。

```powershell
& web/scripts/run-dev.ps1 -Service api
& web/scripts/run-dev.ps1 -Service worker
& web/scripts/run-dev.ps1 -Service frontend
```

4. 按当前任务检查实际页面和受影响接口。涉及生产操作时，先按[部署位置](MAP.md#安装与部署)核对目标与方式，并分别记录部署和验证结果。
