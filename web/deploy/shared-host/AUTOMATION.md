# GitHub 自动部署

[网站流水线](../../../.github/workflows/deploy-web.yml) 针对 `main` 的 `web/**` 或流水线自身
变更运行，也可在 Actions 手动运行。PR 只检查；推送或合入 main 后，检查全部通过才发布。
Windows 客户端安装包仍按原发行流程处理，此工作流只发布网站。

检查包含前端类型生成、TypeScript、ESLint、锁定契约一致性、生产依赖审计、Go vet、
独立 PostgreSQL 16 的完整后端测试、Go 漏洞检查、发布安全/恢复回归、Linux 镜像构建、
桌面与手机共 14 组真实浏览器检查。检查任务没有生产 secrets，数据库口令逐次随机生成。

## GitHub 配置

`production` environment 只允许 `main`，无额外人工批准步骤；里面保存三个独立 secrets：

| 名称 | 作用 |
| --- | --- |
| `DEPLOY_HOST` | 已部署服务器地址 |
| `DEPLOY_SSH_KEY` | 仅能调用发布入口的专用 Ed25519 私钥 |
| `DEPLOY_KNOWN_HOSTS` | 已通过现有可信连接核对的主机公钥，SSH 强制验证 |

数据库、S3、SMTP、OAuth、GitHub 反馈令牌仍仅存服务器的 root 600 环境文件。
Actions 自带权限仅 `contents: read`，不复制本机 CLI 的账号授权。官方 actions 以完整 SHA 固定。

## 主机端

`ci_bundle.py`、`ci_runtime.py`、`ci_deploy.py` 由运维安装到 root 持有的
`/opt/xuansi/deploy/`，权限 755/644。`/usr/local/sbin/xuansi-deploy` 用 Python 隔离模式导入
此目录并调用 `ci_deploy.main()`。它们不从普通 CI 发布包中更新，修改此入口需单独审阅安装。

专用公钥在 root 的 authorized_keys 中使用：

```text
restrict,command="/usr/local/sbin/xuansi-deploy" ssh-ed25519 <专用公钥> xuansi-github-actions
```

此密钥只接受 `status` 和 `deploy <40位提交> <run_id> <attempt>`，不提供普通 shell、
终端或转发能力。发布包只允许六个普通文件；验证身份、大小和 SHA256，拒绝链接和越界路径。
Docker 包只能包含本次 `xuansi-frontend:ci-<commit>` 标签，不能替换其他项目镜像。

GitHub 的生产 job 不互相取消；服务器另以文件锁串行发布，两端都核对 main 最新 SHA，
服务器拒绝更旧的流水线编号。重跑失败的部署可以复用同一次运行已经检查过的 artifact。

候选前端使用 18190/18191 交替端口，以普通用户、只读根文件系统和内存限额运行。
图片缓存为受限 tmpfs。候选就绪后备份数据库、暂停 worker、执行迁移、切换后端链接，
完成 API 和 worker 检查再只替换玄司虚拟主机的前端上游，执行 nginx -t/reload，并在旧容器
仍可恢复的阶段验证公网 HTTPS 页面和 API；公网验收通过才记录成功并停止旧容器。
其他域名、数据库和 MinIO 配置不在自动发布范围。

失败时回到上一版应用与代理并重新检查；数据库不自动执行 down，也不覆盖现有数据。
后续 schema 变更必须保持上一版应用兼容，应用回退不能修复破坏性迁移。备份留在
`/opt/xuansi/backups/web-ci-*`，当前与上一前端容器/镜像保留，不全局清理 Docker 数据。

状态记录在 `/opt/xuansi/shared/deployment-state.json`；GitHub 只显示阶段和提交编号，
原始命令诊断在服务器 root 私有 `deploy-last-error.log`。Secrets 不进入发布包或公开日志。

## 依赖审计边界

部署阻断门检查生产依赖和 Go 实际调用漏洞。2026-10-21 完整开发依赖审计还发现
[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)：ESLint 的
fast-glob/micromatch 间接使用 braces 3.0.3，上游当日尚无修补版本。它只在隔离的检查任务
处理仓库的 lint 模式，不进入 Next standalone 生产依赖；本次记录该开发工具告警，
不把生产审计通过表述为“所有开发依赖零漏洞”。上游提供修补后应更新锁文件并复查。
