# 开发与验证

开发环境、检查入口和改动约定集中在本页；安装与构建步骤见 [安装与发布](../发布与安装/安装与发布.md)。

## 开发约定

以源码和测试说明实际能力，先检查现有模块再修改。保持职责简单、改动可审查，关键路径使用说明原因的注释及运行状态日志，不记录用户聊天、画面或录音正文。

Qt 窗口操作留在主线程，HTTP/子进程优先异步，耗时计算和保存按需放到后台。取消、迟到结果、持久化及原生资源生命周期必须保留原有边界；已经进入线程的短计算或写入不能当作可随时强杀的任务。

根目录用户数据、下载模型和制作中的未跟踪工程不应纳入普通代码提交。具体忽略规则见 [.gitignore](../../.gitignore)，素材授权和第三方范围见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## 基础检查

从已按 `setup.ps1` 建好的项目环境执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check pet tests scripts
.\.venv\Scripts\python.exe -m compileall -q pet scripts tests
```

[pyproject.toml](../../pyproject.toml) 配置 pytest 的 `tests/` 路径和 Ruff 的 Python 3.13、导入及基础错误规则。仓库目前未配置独立静态类型检查器。测试大多使用模拟模型和临时文件；通过不等于真实权重、麦克风、GPU 或安装器验证通过。

按行为变化选择已有回归测试；控制/记忆、在线断句、取消、保存、声音回避和多模型释放都有对应 `tests/test_*.py`。不要为了纯文档变更新增镜像实现的业务测试。

当前 AI 模块的离线入口为 `test_ai_install_plan_rules`（直接调用共享计划规则）、`test_ai_selection`（候选、授权、取消与不重放）、`test_ai_assembly`（生产装配与模拟 HTTP 完整流）和 `test_ai_boundaries`（干净解释器导入）。`test_ai_audio_resources` 与 `test_ai_install` 覆盖语音组件选择及旧设置升级。测试只证明各自范围；不会替代服务商、模型与设备实测。

官网的 Go、前端类型／lint／构建及浏览器检查命令见 [官网运行说明](../官网/本地开发与运行.md#验证入口与边界)。使用独立测试库运行数据库集成，不能将生产连接传入带清理操作的测试。

## 专项验收工具

下面命令在权重及环境已就绪时运行。报告使用新的输出名称，保留旧失败和验收证据。

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/verify_appearance_preview.py --output data/verification/appearance-preview-recheck.json
.\.venv\Scripts\python.exe -X utf8 scripts/verify_native_tools.py --output data/verification/native-protocol-recheck.json
.\.venv\Scripts\python.exe -X utf8 scripts/verify_tool_dialogue.py --suite full --output data/verification/native-dialogue-recheck.json
.\.venv\Scripts\python.exe -X utf8 scripts/verify_tool_dialogue.py --suite speech --output data/verification/native-speech-recheck.json
.\.venv\Scripts\python.exe -X utf8 scripts/verify_business_integration.py --output data/verification/business-integration-recheck.json
```

| 脚本 | 验证范围与实际影响 |
| --- | --- |
| [verify_appearance_preview.py](../../scripts/verify_appearance_preview.py) | Windows/Qt/OpenGL 和本项目 Live2D，使用人工图片；不运行语言模型或启麦，报告及截图落盘 |
| [verify_tool_dialogue.py](../../scripts/verify_tool_dialogue.py) | 模型工具闭环；full 按当前夹具执行负例、工具正例、观察画面、长记忆及暖机性能；`--router` 使用与运行时相同的装配入口。临时记忆、合成截图、模拟动作回执，不实际合成或播放 |
| [verify_native_tools.py](../../scripts/verify_native_tools.py) | 当前引擎的 auto/none/required、工具结果、携图续答和流式参数；只使用合成资料 |
| [verify_model_semantics.py](../../scripts/verify_model_semantics.py) | 兼容迁移入口，默认 full；旧 `--control-only` 转 speech、`--clarify-only` 转 full，保留 `--output`；不重新覆盖历史 Melo→SenseVoice 或 Kokoro 波形 |
| [verify_business_integration.py](../../scripts/verify_business_integration.py) | Qt 窗口与真实模型链、临时配置/记忆、捕获虚拟窗口；报告和截图落盘，音频使用测试接收器 |
| [verify_voice_reliability.py](../../scripts/verify_voice_reliability.py) | 委托原生工具 full 矩阵，支持 `--output`；旧 ASR/低音量/NPZ 重放退役，`--repro-audio` 明确报错，历史报告保留 |
| [verify_model_speech.py](../../scripts/verify_model_speech.py) | 委托原生工具 speech 矩阵：开关、上下文恢复和合成引擎选择；不验证实际音频设备或波形 |
| [verify_speech_ui.py](../../scripts/verify_speech_ui.py) | 原生 Qt 朗读开关与状态同步；模型原生工具替身、临时记忆及静音接收器，不启动 GPU 或真实麦克风 |
| [verify_observation.py](../../scripts/verify_observation.py) | 受控静默协议、真实自然观察、独立显式看图三阶段；真实截图仅允许完整覆盖的人工窗口，使用临时记忆；受控静默不计作真实模型语义通过 |
| [verify_ai_setup_ui.py](../../scripts/verify_ai_setup_ui.py)、[verify_desktop_design.py](../../scripts/verify_desktop_design.py) | 原生 Qt 表单、状态与布局检查；运行前核对各自隔离方式和截图输出，不等同于真实 API 或完整正式安装 |
| 其他 [scripts/](../../scripts) 验收脚本 | 观察、菜单、形象、资源或音频专项；运行前读取脚本确认是否启麦、播放、截图及是否改写固定报告 |

真实模型检查占 GPU 和内存，原生窗口检查需要可用 Windows 桌面。不同脚本的数据隔离程度不同，不能笼统承诺所有验收工具都无副作用；普通单元测试不会替代真实声音听感、多屏混合 DPI 或日常流畅度评估。

历史模型报告、失败及性能测量见 [候选验收](../归档/对话与记忆/验收/模型自主工具对话候选验收-2026-10-16.md)，不在开发指南重复维护各轮数值。

## 生产入口冒烟

```powershell
.\.venv\Scripts\python.exe -m pet --smoke
```

该入口使用全套默认 `Settings`，其中设 `observe=False`，不加载已保存配置，并计划五秒退出；仍使用正常根目录的日志、实例锁和长期记忆路径。运行前退出同目录桌宠，否则只通知已有面板；它不是完整数据隔离模式，也不验证真实图文/语音能力。需要观察面板可用 `--panel`，但这仍是普通应用启动。

## 构建检查

[构建脚本](../../scripts/build_installer.ps1) 要求 Git 可见工作树干净，从 HEAD 导出；不带测试或发布步骤。完整命令、依赖、排除表、产物及升级边界见 [安装与发布](../发布与安装/安装与发布.md#构建与发布)。

不要将安装目录 `release.json.commit`、分支 HEAD 和 GitHub Release 混用。验证安装包时应在隔离目录核对实际包来源及保留的数据摘要；本次文档整理没有重新执行历史安装复验。

本地源码预览更新通过独立备份、精确提交导出、文件摘要与关闭观察的生产冒烟验证，记录 `release.json.channel=local-preview`。保留基础版本号不能说明与同名公开安装包相同，应同时核对提交与渠道。本次更新事实见 [同步记录](../客户端/任务/模块文档与本地同步-2026-10-18.md)。

## 文档维护

现行文档各自维护一份事实：使用指南说明用户操作，配置文档说明字段和数据，架构文档说明模块与生命周期，安装文档说明下载、安装和发行。入口见 [文档索引](../README.md)。

完成的任务与旧验收进入 [归档](../归档/README.md)，保留原范围、日期、失败、提交和摘要。Wiki 只保留简短决策及权威链接，约定见 [[文档目录与维护约定]]。

移动或合并时同步检查 Markdown/HTML 链接、锚点、Wiki sources、索引和构建输入；保留安装须知、许可和机器接口契约的功能位置。纯文档变更检查这些边界，不重复执行无关 GPU 或业务验收。
