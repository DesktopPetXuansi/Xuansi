# 玄司 Xuansi · 本地 AI 桌宠

玄司是运行在 Windows 上的桌面 AI 伙伴，支持屏幕理解、文字聊天、说完后回复的连续语音、明确授权的长期记忆和 Live2D 形象。名字、人设、模型参数、声音和形象可在软件中调整。首次安装联网下载，日常推理在本机运行，无需云端账号或 API 密钥。

<p align="center">
  <img src="assets/xuansi/front.png" alt="玄司：黑发高马尾、黑金古风服装的桌面伙伴" width="220">
</p>

## 版本与发布

源码及现行指南为 **0.5.6**。本版将自动语音附图、记忆相关性、保存澄清及自动朗读引擎选择交给现有 Qwen，并纳入原生验收共享上下文与截图检查修复、旧语音语法及闲置 Neko ICO 清理。

公开安装包以 [GitHub Latest](https://github.com/DesktopPetXuansi/Xuansi/releases/latest) 为准；本版来源、摘要、安装和公开验证见 [0.5.6 发布验收](安装包0.5.6发布验收.md)。安装目录的 `release.json` 记录实际版本及提交。

[首次文档核对](docs/文档核对记录-2026-10-11.md) 与 [历史本地安装验收](安装包0.5.6验收.md) 保留发布前快照，不代表后续正式包来源；历史实现差异见 [更新记录](CHANGELOG.md)。

## 已实现能力

- 屏幕理解：鼠标点击、拖拽结束、滚动和停留触发观察；整块显示器或鼠标附近两种范围，也可手动附图提问。
- 聊天与记忆：本地图文对话、近期会话上下文；明确请求保存或手动编辑长期记忆，含糊时先询问。
- 连续语音：手动启麦、实时转写、话段结束后生成并分段朗读。提交后暂停收音，回复处理及播放完成再恢复；不支持全双工口头插话。
- 角色动画：默认 Live2D 眨眼、视线、响度口型及发丝衣摆摆动；直接动作请求目前只开放一次眨眼。满足空闲条件后播放预制拔刀姿态。
- 形象替换：导入静态图片或透明 GIF/WebP/APNG，预览后应用；默认预览支持独立眨眼按钮。
- 桌面控制：托盘、快捷对话、日志、配置、声音回避、休眠与资源释放；启动不自动开启麦克风。
- 官网资源（源码新增）：托盘中连接官网账号，直接选择本地 Live2D 模型文件夹或入口文件上传，自动整理、校验与加入资源库；也支持资源下载安装及离线使用。[客户端上传说明](web/docs/客户端上传.md)。现行公开0.5.6安装包尚未包含此入口。

详细操作与能力边界见 [使用指南](docs/使用指南.md)，模块及调用顺序见 [项目文档](项目文档.md)。

## 下载与安装

下载 [Windows x64 在线安装包 0.5.6](https://github.com/DesktopPetXuansi/Xuansi/releases/download/v0.5.6/Xuansi-0.5.6-windows-x64-setup.exe) 和 [SHA256SUMS.txt](https://github.com/DesktopPetXuansi/Xuansi/releases/download/v0.5.6/SHA256SUMS.txt)，或查看 [GitHub Releases](https://github.com/DesktopPetXuansi/Xuansi/releases/latest)。安装包内置 Python 3.13.15，无需预装 Python 或 Git。

当前安装路线要求 **Windows 11 x64、兼容 CUDA 12.4 的 NVIDIA GPU 与驱动、D 盘**。建议至少预留 15GB 空间；模型固定放在 `D:\AI\Models\desktop-pet`，应用盘还需容纳环境与推理引擎。首次下载需要网络，不是离线安装包。

安装完成后从开始菜单“玄司 AI 桌宠”启动。升级前从托盘退出旧实例，再选择原安装目录安装；程序没有自动更新或跨目录数据迁移功能。包版本及来源查看安装目录的 `release.json`。

完整前提、校验、源码安装、升级保留范围及构建步骤见 [安装与发布](docs/安装与发布.md)。

## 从源码运行

准备 Git 和 64 位 Python 3.13，执行：

```powershell
git clone https://github.com/DesktopPetXuansi/Xuansi.git
cd Xuansi
py -3.13 --version
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
.\.venv\Scripts\pythonw.exe -m pet
```

脚本创建项目内 `.venv` 并下载全部预设模型，包括可选 Kokoro；不设置开机启动。没有 D 盘时，需先按 [源码安装说明](docs/安装与发布.md#源码安装) 同步调整两处模型根目录；软件配置不能移动全部语音模型。

## 文档与开发

[文档索引](文档索引.md) 是全部现行说明、素材说明和历史证据的入口。常用文档：

- [使用指南](docs/使用指南.md)：聊天、语音、记忆、观察、形象与桌面行为。
- [配置与数据](docs/配置与数据.md)：全部默认值、校验范围、保存行为、文件与数据边界。
- [项目文档](项目文档.md)：架构、模块、调用链、并发与当前限制。
- [故障排查](docs/故障排查.md)：安装、收音、朗读、配置、形象与资源问题。
- [开发与验证](CONTRIBUTING.md)：开发检查、验收脚本、构建和文档维护规则。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check pet tests scripts
```

历史测试数量和延迟仅代表对应版本及测试条件，不是当前设备的性能保证。

## 许可

原创代码和文档采用 [Apache-2.0](LICENSE)，来源声明见 [NOTICE](NOTICE)。**玄司图片及其 Live2D 派生素材保留版权**，见 [素材声明](assets/xuansi/LICENSE)；历史 NekoAI 素材保留 MIT。模型、Qt、Live2D、语音资源和 CUDA 各自适用第三方条款，完整范围见 [THIRD_PARTY.md](THIRD_PARTY.md)。
