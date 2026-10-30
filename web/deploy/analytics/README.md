# 可选的匿名访问与下载统计

官网管理员的“访问统计”从 Umami 读取访客估算、浏览量和趋势，从 GitHub 读取正式
Windows 安装包附件的累计下载计数。本目录只部署统计服务；官网 API、worker、前端和
数据库继续由原发布流程管理。四项官网 `UMAMI_*` 配置默认留空，统计未启用时不影响
网页或安装包下载。

Umami 固定为官方 `ghcr.io/umami-software/umami:3.4.1`，与本次接口适配使用的源码一致。
Compose 自带独立的 PostgreSQL 16 和持久卷，数据库不发布端口。虽然共享主机已有
PostgreSQL，此处选择隔离统计迁移与权限，避免误用官网的业务库。资源不足时可以改接
已有服务器上的**独立数据库和独立账号**，但须先核验网络、备份和权限，再调整模板；
不能让 Umami 在官网数据库内建表。

## 初始化服务

下列命令在 Linux 主机执行，示例目录为 `/opt/xuansi/analytics`。先将本目录的
`compose.yaml` 复制到该目录；本步骤不改动现有官网虚拟主机或发布服务。

```sh
install -d -m 700 /opt/xuansi/analytics /opt/xuansi/shared
umask 077
cat > /opt/xuansi/shared/analytics.env <<EOF
UMAMI_BIND_ADDRESS=127.0.0.1
UMAMI_DB_PASSWORD=$(openssl rand -hex 32)
UMAMI_APP_SECRET=$(openssl rand -hex 32)
UMAMI_TWO_FACTOR_KEY=$(openssl rand -hex 32)
EOF
docker compose --env-file /opt/xuansi/shared/analytics.env -f /opt/xuansi/analytics/compose.yaml config --quiet
docker compose --env-file /opt/xuansi/shared/analytics.env -f /opt/xuansi/analytics/compose.yaml pull
docker compose --env-file /opt/xuansi/shared/analytics.env -f /opt/xuansi/analytics/compose.yaml up -d --wait
```

环境文件保持仅 root 可读；不要运行会把展开后的环境值输出到日志的 `docker compose config`
或 `docker inspect`。命令中的数据库密码使用随机十六进制，连接串不需要额外 URL 转义。
认证密钥和双因素加密密钥应稳定保存于秘密备份中。

先通过 SSH 本机端口转发访问 `http://127.0.0.1:18192`，在公开代理之前完成初始化：

```sh
ssh -L 18192:127.0.0.1:18192 your-server
```

Umami 首次创建的账号是 `admin`，默认密码是 `umami`。首次登录立即修改密码，可启用
双因素认证；不要将默认账号直接暴露到公网。新增网站时填写实际官网域名，例如
`xuansi.kukude.top`，记录网站 ID。为后台读取创建单独的普通 Umami 用户并仅授予此网站
的查看权限，在该用户的 Settings → API keys 创建密钥。不要用管理员的全权限 API key。
不要开启公开分享、会话回放、账号识别或额外采集功能。

## 公开脚本与共享主机代理

1. 为统计选择独立 HTTPS 域名，例如 `stats.example.com`，配置 DNS；若使用 Cloudflare，
   选择 Full (strict)，准备覆盖**该统计域名**的源站证书。原官网证书不一定覆盖新子域名。
2. `nginx.conf.example` 替换域名和证书路径后，作为单独虚拟主机放入现有 Nginx 的
   `conf.d`，不要覆盖官网的虚拟主机。模板已核对 Cloudflare 官方 IP 列表；维护时再次核对。
   可信来源检查后，Nginx 覆盖 `X-Real-IP`，Umami 用它估算访客，不能原样信任浏览器的转发头。
3. 当前共享主机的 Nginx 运行在容器内；保持统计端口绑定宿主机 `127.0.0.1`，
   用 `docker network connect xuansi-analytics_default nginx` 将 Nginx 加入统计专用网络。
   Nginx 经 Docker 内部 DNS 访问 `umami:3000`，仅向公网转发 `/script.js` 和 `/api/send`，
   其余路径返回 404；官网 API 经宿主机回环地址访问统计 API。重建 Nginx 容器后须重新
   加入该网络。若 Nginx 直接运行在宿主机，改用回环地址作为代理上游。
4. 在主机上执行 `docker exec nginx nginx -t`，通过后 reload。对统计域名不要缓存
   `/api/*`、加交互式挑战或注入另一份统计脚本；保留 Umami 对 `/api/send` 的 OPTIONS/POST
   响应，浏览器跨域采集需要它们。直接 DNS 模式也可使用此模板，非 Cloudflare 来源的
   `CF-Connecting-IP` 不会被信任。

HTTPS 代理验证后，在官网受限的 `/opt/xuansi/shared/web.env` 添加以下四项。该文件同时由
systemd 与发布工具读取，值需使用 JSON 字符串引号，示例不是可用凭据：

```dotenv
UMAMI_PUBLIC_URL="https://stats.example.com"
UMAMI_API_URL="http://127.0.0.1:18192"
UMAMI_WEBSITE_ID="网站设置中的UUID"
UMAMI_API_KEY="单独查看账号创建的API密钥"
```

`UMAMI_PUBLIC_URL` 仅包含浏览器可访问的 HTTPS 来源，不带路径、查询或片段；官网根据它
生成 `/script.js` 地址。`UMAMI_API_URL` 是 Go 服务访问 Umami 的来源，不追加 `/api`。
只有网站 ID 和公开脚本地址可返回给浏览器，API key 始终留在 Go 环境中。
使用五服务官网 Compose 时，将这四项加入仓库外的生产环境文件后重新创建官网 API；
模板已将变量转交 API/worker，不需要重新构建前端。shared-host 方式重启 `xuansi-api`
即可读取新配置，worker 不采集页面统计。

## 启用验证

- 检查容器健康及 `/api/heartbeat`；浏览器读取官网 `/api/v1/analytics/config` 应仅含
  `enabled`、网站 ID 与脚本地址。配置为空时应返回 `enabled: false`。
- 普通浏览器访问首页、下载页及站内导航后，管理员打开 `/admin/analytics`，核对近 7/30/90 天
  的访客估算与浏览趋势；“下载点击”与“GitHub 下载次数”分开显示。数据可能因浏览器阻止
  脚本、网络或去重方式而有差异，不能代表真实人数或成功安装数。
- 本站采集代码仅允许公开页面，去除查询、片段、来源、标题和账号字段，不调用 `identify`。
  检查登录、个人空间、后台及反馈管理页没有采集请求；停掉统计服务后仍应能正常下载。
- Umami 数据从启用时开始累积，不补造历史；GitHub 下载计数包含直接访问 GitHub 的来源。
  原 Cloudflare Web Analytics 可以保留，但两者口径不同，不相加。

## 备份、更新与停用

维护日志由 Docker 收集并按大小轮转；Nginx 示例不记录访问 IP、来源或查询参数。
不要开启包含请求正文、认证头或 SQL 参数的诊断日志。给统计库制定保存期限、定期备份
并清理到期备份；Umami 的匿名标识轮换不会删除已有统计记录。

更新 Umami 前，先备份独立数据库、当前镜像版本和两个稳定密钥。在已限制访问的目录
使用以下命令生成数据库备份，不在网页或 CI 日志打印内容：

```sh
set -eu
umask 077
install -d -m 700 /opt/xuansi/backups/analytics
analytics_backup_path="/opt/xuansi/backups/analytics/umami-$(date -u +%Y%m%dT%H%M%SZ).pgdump"
(set -C; docker compose --env-file /opt/xuansi/shared/analytics.env -f /opt/xuansi/analytics/compose.yaml exec -T db pg_dump -U umami -d umami -Fc > "$analytics_backup_path")
docker compose --env-file /opt/xuansi/shared/analytics.env -f /opt/xuansi/analytics/compose.yaml exec -T db pg_restore --list < "$analytics_backup_path" > /dev/null
```

复制此备份到隔离 PostgreSQL 实例，运行 `pg_restore` 并验证报表后，才视为备份可恢复。
更新时显式改固定镜像版本，先在隔离环境核对官网聚合 API 的响应和迁移结果；Umami
启动会运行其数据库迁移，不能只降级镜像来回退已升级的库。需要退回旧版本时，应在隔离
环境验证“旧镜像 + 升级前备份”的恢复组合，再切换统计入口。

临时停用时，清空官网四项 `UMAMI_*` 并重启 API，使公开采集配置关闭；随后执行：

```sh
docker compose --env-file /opt/xuansi/shared/analytics.env -f /opt/xuansi/analytics/compose.yaml down
```

此命令保留 `umami_data` 卷。不要附加 `--volumes`；官网、已有统计库和备份均不需要删除。
移除单独统计虚拟主机前，先检查 Nginx 配置。GitHub 下载量读取仍可独立工作。

## 官方依据

- [Umami 3.4.1 Compose](https://github.com/umami-software/umami/blob/v3.4.1/docker-compose.yml)
  与 [Dockerfile](https://github.com/umami-software/umami/blob/v3.4.1/Dockerfile)：启动、数据库、健康检查及镜像运行用户。
- [3.4.1 镜像发布流程](https://github.com/umami-software/umami/blob/v3.4.1/.github/workflows/cd.yml)：
  版本标签去除 `v` 前缀，因此镜像固定为 `:3.4.1`。
- [环境变量](https://docs.umami.is/docs/environment-variables)、[API 认证](https://docs.umami.is/docs/api/authentication)、
  [指标定义](https://docs.umami.is/docs/metric-definitions)：认证密钥、API key、IP 处理与访客估算口径。
