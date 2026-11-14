# 项目映射

## 桌面客户端

| 定位目的 | 源码位置 |
| --- | --- |
| 启动及运行 | [桌面入口](../../pet/__main__.py)、[运行协调](../../pet/runtime.py) |
| 配置与偏好 | [配置](../../pet/config.py)、[偏好](../../pet/preferences.py) |
| 配置安装环境与资源 | [安装脚本](../../setup.ps1)、[Python 依赖锁](../../requirements.lock.txt)、[资源清单](../../assets-manifest.json) |
| 开发检查配置 | [pyproject.toml](../../pyproject.toml) |

## 官网与资源平台

- 前端、Go 后端和 OpenAPI 由[玄司官网私有仓库](https://github.com/DesktopPetXuansi/xuansi_Web)维护。客户端安装器所需的[模型校验样例](../../web/contracts/fixtures/model-references.json)也保留在桌宠仓库。
- 本地环境变量以 [web 配置示例](https://github.com/DesktopPetXuansi/xuansi_Web/blob/main/web/.env.example) 为入口。只按任务核对所需的配置项。

## 安装与部署

- 客户端源码声明版本见 [VERSION](../../VERSION)。安装副本核对其 `release.json`，公开版本按 [README 的发行入口](../../README.md#版本与发布)核对。
- Windows 安装包的文件布局以[安装器定义](../../installer/online.iss)为准，安装前提示来自[安装须知](../../installer/安装须知.txt)，随包许可来源见[第三方许可](THIRD_PARTY.md)。商店包文档输入位置见[暂存脚本](../../scripts/stage_store_payload.py)。
- 官网开发容器、生产模板和主机切换步骤见[官网自动部署](https://github.com/DesktopPetXuansi/xuansi_Web/blob/main/web/deploy/shared-host/AUTOMATION.md)。迁移与生产核验状态见[当前工作](NOW.md)。
