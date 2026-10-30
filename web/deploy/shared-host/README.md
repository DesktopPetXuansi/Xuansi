# 复用现有主机服务

此部署与五服务 Compose 二选一，复用已有 Nginx、PostgreSQL 和 MinIO。API/worker
由 systemd 以 `xuansi-web` 身份运行，Next standalone 使用 Linux Node 24 镜像。
日志由 journald / Docker 收集；Nginx 日志不记录查询字符串，避免泄露签名与一次性令牌。

日常更新使用 [GitHub 自动部署](AUTOMATION.md)：main 的网站变更先检查和构建，再通过
受限发布密钥更新，失败恢复上一版应用。下面保留主机初装与服务布局说明。

管理员的匿名访问统计可按 [独立 Umami 部署](../analytics/README.md) 另行启用；
默认关闭，不随官网更新创建统计库或修改虚拟主机。

- API 监听 `172.17.0.1:18189`，Next 容器只发布 `172.17.0.1:18190:3000`。
- `/opt/xuansi/shared/web.env` 为 root:root 600，保持正式 HTTPS/S3/SMTP 配置校验。
- `/opt/xuansi/web-current` 指向已校验 SHA256 的不可变发布目录。
- API 的 `TRUSTED_PROXY_CIDRS` 只填写实际 Nginx 容器地址；重建代理后重新核对。
- S3 使用私有 `xuansi-resources` 桶及仅限此桶的读写删除凭据；同域路径原样代理。
- 后台 `S3_ENDPOINT=http://127.0.0.1:19000`，浏览器预签名使用
  `S3_PUBLIC_ENDPOINT=https://xuansi.kukude.top`，避免代理改写后台签名请求头。
- Cloudflare 代理下设置 `MAX_UPLOAD_BYTES=100000000`，Nginx 限制与其一致。
- 构建在受 CPU/内存限制的独立 Linux 容器进行。运行前复制 `public` 和 `.next/static`
  到 standalone 内，再用 `frontend-runtime.Dockerfile` 构建最终运行镜像。

切换前备份数据库、原虚拟主机及环境文件，先验证内网 API `/readyz` 和 Next 页面。
然后停止旧 `xuansi-feedback.service`，启用完整 worker，并替换**仅玄司域名**的 Nginx
虚拟主机。旧反馈 worker 会领取其他种类的任务，不能与完整网站共用队列并行运行。

回退页面入口时保留完整 API/worker：恢复原反馈虚拟主机并把其中上游端口改为完整 API
端口 18189，核验 `nginx -t`、reload 结果及 API 就绪；旧反馈进程保持 disabled，
避免新资源任务被旧进程领取。只有任务排空或旧进程明确限制为反馈任务后才能单独评估
恢复旧运行方式，不自动执行 SQL down 迁移。每次上线检查页面、静态资源、图像优化、身份边界、S3 公网
签名上传、校验及下载，并核对旧反馈记录和任务状态。
