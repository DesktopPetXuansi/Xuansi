# 开发与验证

核对日期：2026-10-17。0.6.0 默认采用 Qwen3.5-9B Q4_K_M 与匹配投影，包含原生工具对话、标签栏控制中心及官网资源接入。用户已于 2026-10-17 接受已知差异并授权更新本机和 Release；实际版本及源码来源以安装目录 `release.json` 和 [GitHub v0.6.0](https://github.com/DesktopPetXuansi/Xuansi/releases/tag/v0.6.0) 为准，构建、安装和公开状态见 [0.6.0 发布验收](../发布与安装/验收/安装包0.6.0发布验收.md)。 实现与已知差异见 [模型自主工具对话](../对话与记忆/模型自主工具对话.md)，使用、配置和架构入口见 [文档索引](../README.md)。

## 开发约定

以源码和测试说明实际能力，先检查现有模块再修改。保持职责简单、改动可审查，关键路径使用说明原因的注释及运行状态日志，不记录用户聊天、画面或录音正文。

Qt 窗口操作留在主线程，HTTP/子进程优先异步，耗时计算和保存按需放到后台。取消、迟到结果、持久化及原生资源生命周期必须保留原有边界；已经进入线程的短计算或写入不能当作可随时强杀的任务。

根目录用户数据、下载模型和制作中的未跟踪工程不应纳入普通代码提交。具体忽略规则见 [.gitignore](../../.gitignore)，素材授权和第三方范围见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## 基础检查

从已按 `setup.ps1` 建好的项目环境执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check pet tests scripts
```

[pyproject.toml](../../pyproject.toml) 配置 pytest 的 `tests/` 路径和 Ruff 的 Python 3.13、导入及基础错误规则。仓库目前未配置独立静态类型检查器。测试大多使用模拟模型和临时文件；通过不等于真实权重、麦克风、GPU 或安装器验证通过。

按行为变化选择已有回归测试；控制/记忆、在线断句、取消、保存、声音回避和多模型释放都有对应 `tests/test_*.py`。不要为了纯文档变更新增镜像实现的业务测试。

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
| [verify_tool_dialogue.py](../../scripts/verify_tool_dialogue.py) | 原生模型工具闭环；full 为54次负例、工具正例、观察画面、长记忆及暖机性能。临时记忆、合成截图、模拟动作回执，不实际合成或播放 |
| [verify_native_tools.py](../../scripts/verify_native_tools.py) | 当前引擎的 auto/none/required、工具结果、携图续答和流式参数；只使用合成资料 |
| [verify_model_semantics.py](../../scripts/verify_model_semantics.py) | 兼容迁移入口，默认 full；旧 `--control-only` 转 speech、`--clarify-only` 转 full，保留 `--output`；不重新覆盖历史 Melo→SenseVoice 或 Kokoro 波形 |
| [verify_business_integration.py](../../scripts/verify_business_integration.py) | Qt 窗口与真实模型链、临时配置/记忆、捕获虚拟窗口；报告和截图落盘，音频使用测试接收器 |
| [verify_voice_reliability.py](../../scripts/verify_voice_reliability.py) | 委托原生工具 full 矩阵，支持 `--output`；旧 ASR/低音量/NPZ 重放退役，`--repro-audio` 明确报错，历史报告保留 |
| [verify_model_speech.py](../../scripts/verify_model_speech.py) | 委托原生工具 speech 矩阵：开关、上下文恢复和合成引擎选择；不验证实际音频设备或波形 |
| [verify_speech_ui.py](../../scripts/verify_speech_ui.py) | 原生 Qt 朗读开关与状态同步；模型原生工具替身、临时记忆及静音接收器，不启动 GPU 或真实麦克风 |
| [verify_observation.py](../../scripts/verify_observation.py) | 受控静默协议、真实自然观察、独立显式看图三阶段；真实截图仅允许完整覆盖的人工窗口，使用临时记忆；受控静默不计作真实模型语义通过 |
| 其他 [scripts/](../../scripts) 验收脚本 | 观察、菜单、形象、资源或音频专项；运行前读取脚本确认是否启麦、播放、截图及是否改写固定报告 |

真实模型检查占 GPU 和内存，原生窗口检查需要可用 Windows 桌面。不同脚本的数据隔离程度不同，不能笼统承诺所有验收工具都无副作用；普通单元测试不会替代真实声音听感、多屏混合 DPI 或日常流畅度评估。

2026-10-16 候选 full 首轮报告 `data/verification/native-tools-full-first.json` 为 119 项、30 项失败；`native-tools-full-prompt2.json` 为 119 项、21 项失败；来源分离后的 `native-tools-full-source3.json` 为 119 项、18 项失败；严格提示定向复验 `strict-targeted4.json` 为 15 项、4 项失败，均为 `passed=false`。来源分离后 54 次负例仍有两次错误动作模拟受理；定向报告的 `negative_cases.runs=0` 不包含 `praise/` 命名案例，不能据此宣称零误执行。独立源码完整 pytest 为 500 passed、2 skipped；原项目含用户 12 项未提交 UI 增量为 512 passed、2 skipped，二者 Ruff 均通过。未提交 UI 增量不进入本包，这些结果不替代语义验收。分类、测量和剩余问题见[候选验收记录](../对话与记忆/验收/模型自主工具对话候选验收-2026-10-16.md)。报告位于本机忽略目录，继续复验另存名称，不能删改失败预期换取通过。

三个历史迁移入口默认输出 `*-native-tools-report.json`，不覆盖旧日期报告。新 full/speech 报告不包含历史短句识别、轻声 ASR、旧失败 NPZ 重放或实际 Kokoro/Melo 波形合成，不能据此宣称旧语音专项重新通过；实际音频和听感需要单独验收。

后续 `scope-reasoning-direct.json`、`scope-reasoning-thinking512.json`、`scope-reasoning-thinking1024.json` 各含 25 项局部诊断，失败数分别为 12、3、0。生产入口采用单次原生请求的明确 1024 token 思考预算，容量计算也包含真实总生成额度，未新增前置分类。局部结果不等于完整 full 通过，各轮结果见候选验收；9B 主体保真 full 保留 119 项／1 项脚本失败，119 项已人工审阅，14 条记忆的人物、角色及否定关系逐项正确；三项英文译句沿用 fast 的 P3 保留。其后仅调整观察结束协议，33 项观察和 22 项新表达分组复验通过；语音 6 项仍有 1 项纯英文未选 natural 而沿用 fast。未重新完整跑过 119 项，不能称全部语义全绿。 真实 Runtime + TTS 的 `dialogue-benchmark-terminal-9b.json` 十轮均通过、每轮一次生成请求，首文字／首波形／总耗时中位数为 1.6029／1.88525／3.6668 秒，正文长度中位数 27 字；此前 9B 首波形中位数 3.26355 秒也保留。播放端为模拟接收器，不能据此判断听感或保证延迟无退化。

## 生产入口冒烟

```powershell
.\.venv\Scripts\python.exe -m pet --smoke
```

该入口使用全套默认 `Settings`，其中设 `observe=False`，不加载已保存配置，并计划五秒退出；仍使用正常根目录的日志、实例锁和长期记忆路径。运行前退出同目录桌宠，否则只通知已有面板；它不是完整数据隔离模式，也不验证真实图文/语音能力。需要观察面板可用 `--panel`，但这仍是普通应用启动。

## 构建检查

[构建脚本](../../scripts/build_installer.ps1) 要求 Git 可见工作树干净，从 HEAD 导出；不带测试或发布步骤。完整命令、依赖、排除表、产物及升级边界见 [安装与发布](../发布与安装/安装与发布.md#构建与发布)。

不要将安装目录 `release.json.commit`、分支 HEAD 和 GitHub Release 混用。验证安装包时应在隔离目录核对实际包来源及保留的数据摘要；本次文档整理没有重新执行历史安装复验。

## 文档维护

[文档索引](../README.md) 统一列出资料，现行说明各自维护一份事实：

- README：项目入口和公开下载。
- 使用指南：用户操作。
- 配置与数据：完整字段、持久化和数据路径。
- 项目文档：架构、调用链、限制。
- 安装与发布：环境、下载、构建及安装生命周期。
- Live2D 制作规格及素材 README：绑定、运行与制作来源。
- 历史方案与验收：保留当时范围、失败、测试数量、耗时和摘要。

更新时核对本地已提交与未提交状态，fetch 远程并检查主分支、其他分支和 Release；外部行为或许可用官方文档/上游源码核查。合并旧文档要保留独有证据并改写所有本地链接，不能把计划当成已实现功能。

文档检查至少包括本地链接与锚点、文档索引覆盖、配置字段覆盖、命令参数和版本一致性；本次可复用的整理及验证结果见 [文档核对记录](../文档维护/文档核对记录-2026-10-11.md)。记录检查实际做了什么，未执行的模型、原生窗口或安装验收明确分开。
