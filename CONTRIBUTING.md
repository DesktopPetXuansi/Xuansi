# 开发与验证

当前项目为 Windows/Python 3.13/PySide6 应用，不是 Node 或 Rust 工程。核对日期：2026-10-11；目录、线程和调用链见 [项目文档](项目文档.md)，环境准备见 [安装与发布](docs/安装与发布.md)。

## 开发约定

以源码和测试说明实际能力，先检查现有模块再修改。保持职责简单、改动可审查，关键路径使用说明原因的注释及运行状态日志，不记录用户聊天、画面或录音正文。

Qt 窗口操作留在主线程，HTTP/子进程优先异步，耗时计算和保存按需放到后台。取消、迟到结果、持久化及原生资源生命周期必须保留原有边界；已经进入线程的短计算或写入不能当作可随时强杀的任务。

根目录用户数据、下载模型和制作中的未跟踪工程不应纳入普通代码提交。具体忽略规则见 [.gitignore](.gitignore)，素材授权和第三方范围见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## 基础检查

从已按 `setup.ps1` 建好的项目环境执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check pet tests scripts
```

[pyproject.toml](pyproject.toml) 配置 pytest 的 `tests/` 路径和 Ruff 的 Python 3.13、导入及基础错误规则。仓库目前未配置独立静态类型检查器。测试大多使用模拟模型和临时文件；通过不等于真实权重、麦克风、GPU 或安装器验证通过。

按行为变化选择已有回归测试；控制/记忆、在线断句、取消、保存、声音回避和多模型释放都有对应 `tests/test_*.py`。不要为了纯文档变更新增镜像实现的业务测试。

## 专项验收工具

下面命令在权重及环境已就绪时运行。报告使用新的输出名称，保留旧失败和验收证据。

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/verify_appearance_preview.py --output data/verification/appearance-preview-recheck.json
.\.venv\Scripts\python.exe -X utf8 scripts/verify_model_semantics.py --output data/verification/model-semantics-recheck.json
.\.venv\Scripts\python.exe -X utf8 scripts/verify_business_integration.py --output data/verification/business-integration-recheck.json
```

| 脚本 | 验证范围与实际影响 |
| --- | --- |
| [verify_appearance_preview.py](scripts/verify_appearance_preview.py) | Windows/Qt/OpenGL 和本项目 Live2D，使用人工图片；不运行语言模型或启麦，报告及截图落盘 |
| [verify_model_semantics.py](scripts/verify_model_semantics.py) | 真实 Qwen/mmproj、合成图片、控制及临时记忆；Melo→SenseVoice 内存音频往返和 Kokoro 合成，不启麦、不实际播放、不覆盖在线 Paraformer；支持 `--control-only`、`--clarify-only` |
| [verify_business_integration.py](scripts/verify_business_integration.py) | Qt 窗口与真实模型链、临时配置/记忆、捕获虚拟窗口；报告和截图落盘，音频使用测试接收器 |
| [verify_voice_reliability.py](scripts/verify_voice_reliability.py) | 合成语音、识别、控制和自然保存授权；支持 `--repro-audio`，报告名固定，无 `--output` |
| 其他 [scripts/](scripts/) 验收脚本 | 观察、菜单、形象、资源或音频专项；运行前读取脚本确认是否启麦、播放、截图及是否改写固定报告 |

真实模型检查占 GPU 和内存，原生窗口检查需要可用 Windows 桌面。不同脚本的数据隔离程度不同，不能笼统承诺所有验收工具都无副作用；普通单元测试不会替代真实声音听感、多屏混合 DPI 或日常流畅度评估。

## 生产入口冒烟

```powershell
.\.venv\Scripts\python.exe -m pet --smoke
```

该入口使用全套默认 `Settings`，其中设 `observe=False`，不加载已保存配置，并计划五秒退出；仍使用正常根目录的日志、实例锁和长期记忆路径。运行前退出同目录桌宠，否则只通知已有面板；它不是完整数据隔离模式，也不验证真实图文/语音能力。需要观察面板可用 `--panel`，但这仍是普通应用启动。

## 构建检查

[构建脚本](scripts/build_installer.ps1) 要求 Git 可见工作树干净，从 HEAD 导出；不带测试或发布步骤。完整命令、依赖、排除表、产物及升级边界见 [安装与发布](docs/安装与发布.md#构建与发布)。

不要将安装目录 `release.json.commit`、分支 HEAD 和 GitHub Release 混用。验证安装包时应在隔离目录核对实际包来源及保留的数据摘要；本次文档整理没有重新执行历史安装复验。

## 文档维护

[文档索引](文档索引.md) 统一列出资料，现行说明各自维护一份事实：

- README：项目入口和公开下载。
- 使用指南：用户操作。
- 配置与数据：完整字段、持久化和数据路径。
- 项目文档：架构、调用链、限制。
- 安装与发布：环境、下载、构建及安装生命周期。
- Live2D 制作规格及素材 README：绑定、运行与制作来源。
- 历史方案与验收：保留当时范围、失败、测试数量、耗时和摘要。

更新时核对本地已提交与未提交状态，fetch 远程并检查主分支、其他分支和 Release；外部行为或许可用官方文档/上游源码核查。合并旧文档要保留独有证据并改写所有本地链接，不能把计划当成已实现功能。

文档检查至少包括本地链接与锚点、文档索引覆盖、配置字段覆盖、命令参数和版本一致性；本次可复用的整理及验证结果见 [文档核对记录](docs/文档核对记录-2026-10-11.md)。记录检查实际做了什么，未执行的模型、原生窗口或安装验收明确分开。
