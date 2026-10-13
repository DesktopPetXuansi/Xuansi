# 官网部署说明

本项目提供可审阅的生产部署模板。本次完成本机实现与验收，未部署公网服务、配置真实生产存储/邮件，也未发布新的桌面客户端。

## 运行布局

生产使用 `compose.production.yaml`，Go API、worker、PostgreSQL、Next 和 Caddy 为独立进程。只有 Caddy 开放 80/443；数据库和 Go 没有宿主机公开端口。前端服务使用 Next standalone 产物。数据库采用密码认证，文件使用 S3/R2 私有桶。Go 和 Next 容器使用普通用户。

先把 `.env.production.example` 复制到仓库外的受限环境文件，填写实际域名、数据库密码、SMTP、S3 和至少 32 字符的稳定 OAuth 密钥。数据库 URL 中密码按 URL 规则编码。`APP_URL` 必须为官网 HTTPS 来源，`SITE_ADDRESS` 为同一域名。

准备好真实环境后，命令入口为：

```powershell
docker compose --env-file E:/secure/xuansi-production.env -f web/deploy/compose.production.yaml config --quiet
docker compose --env-file E:/secure/xuansi-production.env -f web/deploy/compose.production.yaml up -d --build
```

模板使用 `172.30.253.0/28` 私网，Caddy 固定 `.2`，Next 固定 `.3`。如果该子网与主机网络冲突，一起修改 subnet、两个固定地址及 `TRUSTED_PROXY_CIDRS`。Go 仅信任这两个具体代理，避免伪造 X-Forwarded-For 绕过认证限流。默认不信任其他代理来源。

生产模板把 `APP_URL` 同时传入前端构建参数 `SITE_URL`，用于静态 sitemap/robots 地址。更换域名后重新构建前端，避免静态元数据仍引用旧域名。

API 就绪检查会连接数据库；API 迁移完成并就绪后再启动 worker 与 Next。`/healthz` 只检查进程存活，`/readyz` 检查数据库。任务租约在进程意外退出后允许重新领取，数据库记录是任务状态来源。

## 存储与邮件

S3/R2 桶保持私有。账号凭据只授予指定桶必需的读、写、删除和签名上传能力。浏览器直接向预签名 PUT URL 上传隔离对象，完成请求只排队校验，不直接公开文件。首期不支持分片上传。

配置桶 CORS：允许官网 HTTPS 来源、PUT、HEAD 和返回签名要求的请求头。为 `quarantine/` 前缀配置一天过期的生命周期规则，作为未完成直接上传的清理补充；`packages/` 和 `covers/` 不配置同样的过期规则。

下载使用 Go 的短期票据流式代理。每次使用票据重新检查资源状态和授权，提供及时撤销能力。数据库任务负责超额、取消、失败和封面替换后的对象清理；不会仅因为旧上传被取消就删除当前仍引用的封面。

SMTP 需要可达的实际邮件服务器、发件地址和认证信息；生产路径使用 STARTTLS。配置发件域的邮件认证并实际检查验证与恢复邮件送达。不要使用 Mailpit 作为生产发件服务。成功邮件任务会清空包含一次性链接的任务正文，HTTP 日志不记录 token、Cookie、请求体或下载票据。

## 数据与运行维护

数据库 SQL 迁移嵌入 Go 可执行文件；发布前备份 PostgreSQL，并保持存储对象与数据库引用一致。回滚应用时检查迁移兼容性，不对已有用户数据自动执行 down 迁移。定期保留数据库备份并验证恢复；对象桶根据实际恢复目标配置版本和备份策略。

没有默认管理员口令。先通过官网注册、验证邮箱，再使用 API 容器内的 CLI 提升该账号：

```powershell
docker compose --env-file E:/secure/xuansi-production.env -f web/deploy/compose.production.yaml exec api /app/admin -email 已验证的邮箱
```

首期日志包含请求 ID、路由模板、耗时和任务结果；根据实际部署平台采集，监控 `/readyz`、失败任务、上传清理、数据库容量与存储容量。开发 HTTP、无密码的回环 PostgreSQL 与随机 OAuth 密钥只用于本机。

## 当前验证边界

- 生产 compose 配置解析与环境参数检查通过；Go 二进制、Next 生产构建和本地端到端验证通过。
- Docker Desktop 在本机被残留 IPC 套接字阻塞。已采用官方便携 PostgreSQL/Mailpit 完成本地验收；没有删除容器数据库或重置 Docker。**容器镜像构建和容器内运行未完成验证**。
- S3 SDK 适配有本机协议夹具验证，实际生产 R2/S3、SMTP、域名和 TLS 需要在真实部署环境验收。
- 分发前需确认 Live2D SDK/Core 对资源扩展应用和所用模型的许可条件，并制作带资源接入功能的新客户端发行版。当前官网公开安装器 v0.5.6 尚不包含本次平台入口。
