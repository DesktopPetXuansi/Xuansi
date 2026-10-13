# 玄司官网与资源平台

本目录是 desktop-ai-pet 的配套官网。首期提供产品介绍、真实客户端下载、账号、个人资源工作台、管理员发布及客户端资源接入。用户方案与实施边界见 [官网规划](docs/官网规划.md)，实际接口见 [OpenAPI](contracts/openapi.yaml) 和 [接口约定](contracts/接口约定.md)。

## 已实现的能力

- 注册、邮箱验证、登录、密码恢复、个人资料、会话管理、客户端授权撤销。
- 模型、动作、表情、静态图片、GIF 资源的创建、编辑、版本、封面、上传、删除和个人资源库。
- 隔离上传、后台结构校验、SHA-256、不可变规范 ZIP、精确模型版本依赖、配额预留和结算、取消及失败清理、幂等完成。
- 私有资源所有者隔离；管理员可发布公开资源、隐藏/停用资源、管理用户、编辑版本草稿、发布版本、查看任务和审计。
- 桌面源码已接入系统浏览器 PKCE、Windows 凭据保管、后台下载、安全安装、模型试载、动作/表情应用和离线恢复。入口为托盘菜单中的官网资源库。

公开下载仍指向已经发行的 **v0.5.6 Windows 在线安装器**。官网资源接入属于当前源码新增功能，尚未随新客户端发行。网站模型预览首期使用封面和资源信息；实际 Live2D 渲染在桌面客户端。

商店交易、用户自由公开分享、评论收藏排行、浏览器 Cubism 渲染、分片上传和客户端自动升级属于后续扩展。现有资源/版本/依赖、发布渠道和权限边界可继续演进，无需先引入微服务。

## 技术与架构

| 部分 | 选择 |
| --- | --- |
| 页面 | React 19.3、Next.js 16.4 App Router、TypeScript strict |
| 界面与状态 | Tailwind CSS 4.3、项目自身组件、Lucide、TanStack Query、React Hook Form、Zod |
| 业务服务 | Go 1.26.9、chi、GORM、Goose、Fosite |
| 数据库 | PostgreSQL 18；本机验收使用官方 Windows 18.6 二进制 |
| 文件 | 本地开发目录；生产 S3/R2 私有桶，AWS SDK v2 |
| 邮件与入口 | 本机 Mailpit 1.31；生产 SMTP、Caddy HTTPS |
| 契约 | OpenAPI 3.1、生成的 TypeScript/Go 类型、版本化 manifest JSON Schema |

```mermaid
flowchart LR
  Browser[官网浏览器] --> Entry[Next / Caddy 同源入口]
  Entry --> API[Go API]
  API --> DB[(PostgreSQL)]
  API --> Files[本地 / S3 私有存储]
  Worker[Go worker] --> DB
  Worker --> Files
  Worker --> SMTP[SMTP]
  Pet[桌面客户端] -->|浏览器 PKCE 授权| Entry
  Pet -->|只读授权 / 清单 / 下载票据| API
  Pet --> Local[本地安全资源库 / Live2D]
```

Go 是业务唯一后端；Next 提供页面和同源代理。任务使用 PostgreSQL 队列与租约，worker 通过行锁领取。资源库、客户端版本安装包和资源版本依赖采用批量查询。网络及落盘工作在客户端后台执行，SDK 操作回到 Qt 主线程。平台不上传聊天、截图、录音或 AI 服务密钥。

## 本机启动

需要 Node.js 24、pnpm 11、可自动选择 Go 1.26.9 工具链的 Go 安装。桌面验收另需仓库 Python 虚拟环境、PySide6、live2d-py 和 Chrome。命令在项目根目录执行。

首次安装前端依赖：

```powershell
Push-Location web/frontend
pnpm install --frozen-lockfile
Pop-Location
Copy-Item web/.env.example web/.env
```

数据库和开发邮件常规使用 Docker：

```powershell
& web/scripts/run-dependencies.ps1
```

当前工作区已经准备了便携本机依赖，也可以运行：

```powershell
& web/scripts/run-dependencies.ps1 -Portable
```

便携工具位于忽略目录 `web/.runtime/tools/postgresql/pgsql/bin` 和 `web/.runtime/tools/mailpit/mailpit.exe`，数据位于 `web/.runtime/postgres`、`web/.runtime/mailpit.sqlite3`。新工作区可从 [PostgreSQL 官方 Windows 下载入口](https://www.postgresql.org/download/windows/) 获取 EDB 二进制，从 [Mailpit 官方发行页](https://github.com/axllent/mailpit/releases/tag/v1.31.0) 获取对应工具并放入上述目录。运行脚本只启动本项目数据目录，发现占用邮件端口的其他程序时停止，不操作该程序。

在三个独立终端依次启动 API、worker、前端；API 的 `/readyz` 返回成功后再启动 worker：

```powershell
& web/scripts/run-dev.ps1 -Service api
& web/scripts/run-dev.ps1 -Service worker
& web/scripts/run-dev.ps1 -Service frontend
```

| 服务 | 地址 |
| --- | --- |
| 官网 | http://localhost:3000 |
| Go 存活 / 就绪 | http://127.0.0.1:8080/healthz /readyz |
| 开发邮件捕获界面 | http://127.0.0.1:8025 |
| PostgreSQL | 127.0.0.1:54329；开发库 xuansi |

浏览器使用 `localhost:3000`，保持与 `APP_URL` 相同来源。注册后在邮件捕获界面打开验证链接，再登录。没有默认管理员账号。需先注册并验证实际账号，再在已配置 `DATABASE_URL` 的后端终端提升：

```powershell
Push-Location web/backend
$env:DATABASE_URL='postgres://xuansi@127.0.0.1:54329/xuansi?sslmode=disable'
go run ./cmd/admin -email 已验证的邮箱
Pop-Location
```

API 启动时 `-migrate` 应用嵌入的四个迁移，可重复运行；不使用 AutoMigrate。开发的随机 OAuth 密钥随 API 重启失效，客户端需要重新授权。生产必须配置稳定密钥。

验收生产构建时，在 `web/frontend` 执行 `pnpm build`，关闭正在运行的开发前端，然后在项目根目录运行 `& web/scripts/run-preview.ps1`。它使用与镜像相同的 standalone 入口，仍仅绑定本机；不能与开发前端同时占用 3000 端口。

## 资源协议

模型上传包含 `.model3.json`、`.moc3`、纹理及引用文件的 ZIP；入口不明确时填写入口相对路径。动作上传 `.motion3.json`、表情上传 `.exp3.json`，必须绑定本人或可访问的已就绪模型版本。静态图片/封面支持 PNG、JPEG、WebP，动图首期使用 GIF。

worker 将所有类型转换为带 manifest 的 ZIP。默认上传和解包上限均为 512 MiB，文件数量上限 2048，默认用户配额 2 GiB。平台拒绝路径穿越、符号链接、Windows 非法名称、脚本和保留文件名。`minimumClientVersion` 留空表示未声明最低版本；声明时使用三段数字。

结构校验通过仅表示包完整。版本保持 `UNTESTED`，客户端以实际 SDK 试载判定兼容；试载失败回退。空的可选 Cubism 引用允许，MOC、纹理、动作/表情文件引用必须存在。凭据不写入配置或日志，下载票据短期有效，资源停用或授权撤销后立即拒绝访问。

## 目录

```text
web/
  frontend/              页面、组件、API 调用及锁定依赖
  backend/
    cmd/{api,worker,admin}/
    internal/{api,oauth,platform,resource}/
    migrations/          显式 SQL 迁移与真实发行元数据
  contracts/             OpenAPI、manifest Schema、共享夹具、生成类型
  deploy/                Dockerfile、Caddy、独立生产 compose 和配置示例
  scripts/               启动、契约生成、浏览器/客户端/安装载荷验收
  docs/                  方案、开发验收
  tasks/                 实施计划与验收清单
  DESIGN.md              品牌、布局和交互规范
```

生成类型执行 `& web/scripts/generate-contracts.ps1`；编辑 OpenAPI 后重新生成，不手改生成文件。生成 Go 类型可供服务适配和后续 SDK 使用，当前 API 使用显式业务模型和输入校验。

完整验证命令及结果见 [开发验收](docs/开发验收.md)，生产配置见 [部署说明](deploy/README.md)。`.env`、便携工具、数据库、资源、邮件和验收截图不提交，也不进入桌面安装载荷。
