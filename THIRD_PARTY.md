# 第三方来源与许可范围

核对日期：2026-09-14。本项目原创源代码及文档采用根目录 [Apache-2.0](LICENSE)，不改变第三方代码、模型、数据和图片各自的许可。以下记录来源与已发现的分发边界，不是商业安装包的完整许可审计。

## 主要组件

| 组件 | 来源与版本 | 许可及范围 |
| --- | --- | --- |
| 历史猫精灵、图标、动画定义 | [NekoAI](https://github.com/nucket/NekoAI)，提交 `6c3f1235063ee0748fc710977b0c4a93aa76bdea` | MIT，Copyright (c) 2026 Naudy Castellanos；原文保留于 [assets/neko/LICENSE](assets/neko/LICENSE)，当前默认形象不再加载。开发时的 `upstream-nekoai/` 副本不随本仓库发布 |
| 当前玄司立绘与头像 | 用户角色参考图，经图像工具及授权的本机处理制作，见 [素材来源](assets/xuansi/README.md) | 用户明确要求保留版权，见 [单独声明](assets/xuansi/LICENSE)；不属于 Apache-2.0 或 NekoAI 的 MIT 范围 |
| 图文基础模型 | [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) | Apache-2.0；模型许可仍应随实际分发保留 |
| GGUF 及视觉组件 | [unsloth/Qwen3.5-4B-GGUF](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF)，提交 `e87f176479d0855a907a41277aca2f8ee7a09523` | 上述模型的转换，按 HF LFS 摘要校验，不因格式转换获得新的无限制许可 |
| 推理引擎 | [llama.cpp](https://github.com/ggml-org/llama.cpp)，b10930 Windows CUDA 12.4 | 引擎 MIT；随下载包提供的 CUDA 运行库另受 NVIDIA 条款约束，不能把整个二进制包统称 MIT |
| 语音识别权重 | [SenseVoiceSmall](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)，sherpa-onnx int8 2025-09-09 转换 | 模型卡指向 [FunASR Model License](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE)，不是 Apache-2.0；模型目录中保留 `MODEL_LICENSE` |
| 默认实时识别权重 | [sherpa-onnx-streaming-paraformer-bilingual-zh-en](https://huggingface.co/csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en)，固定提交 `8e40c43232a1c5c66c82111efc5820d3accca11b` | 转换仓库模型卡标注 Apache-2.0，并指向 ModelScope 的 `damo/speech_paraformer_asr_nat-zh-cn-16k-common-vocab8404-online`。该标签是转换仓库声明，商业分发仍需核对原始权重许可与来源；本次未获得新的商业授权。encoder/decoder int8 使用 HF LFS SHA256，tokens 固定版本并校验实际下载摘要 |
| 默认朗读权重 | [MeloTTS](https://github.com/myshell-ai/MeloTTS)、[MeloTTS-Chinese](https://huggingface.co/myshell-ai/MeloTTS-Chinese)，sherpa `vits-melo-tts-zh_en` | MIT；已下载包自带 MyShell.ai 的 LICENSE。中英、44100Hz、单音色 |
| 可选朗读权重 | [Kokoro-82M-v1.1-zh](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)，sherpa int8 multi-lang v1_1 | 模型 Apache-2.0；包内其他语音处理资源需要分别核对，不能只看模型标签 |
| Kokoro 语音处理资源 | 模型包的 `espeak-ng-data`，供当前 Kokoro 初始化使用 | [eSpeak NG 上游 COPYING](https://github.com/espeak-ng/espeak-ng/blob/master/COPYING) 为 GPL-3.0；具体数据文件、链接方式和实际二进制构建的分发义务需单独审计 |
| 语音运行时 | [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)，1.13.8 | 主项目 Apache-2.0；依赖、转换权重和声音资源不因此自动采用相同许可 |
| 界面与绑定 | [Qt for Python / PySide6](https://doc.qt.io/qtforpython-6/licenses.html)，6.11.2 Essentials；Shiboken6 | LGPL-3.0 / GPL-3.0 / 商业许可体系；当前从 pip 动态加载，分发需根据实际组件和方式满足相应义务 |
| Windows 音频会话接口 | [pycaw](https://github.com/AndreMiras/pycaw)，20251023 | MIT；只使用查询和通知接口 |
| Windows COM 桥接 | [comtypes](https://github.com/enthought/comtypes)，1.4.16 | MIT |

全部 Python 依赖的准确版本在 [requirements.lock.txt](requirements.lock.txt)。表格列出主要组件，没有逐一替代这些包及其传递依赖自己的许可文件；制作发行包时应从实际安装产物收集许可证及第三方通知。

## 商业使用时需要区分的事项

### 原创代码和形象

Apache-2.0 允许满足其条款的商业使用及分发，也允许将原创代码用于闭源产品。相关复制、分发、修改标识、NOTICE 和专利条件以 [Apache 官方原文](https://www.apache.org/licenses/LICENSE-2.0) 为准。选择 Apache-2.0 也意味着其他人获得该许可授予的商业使用权；它不授予商标权。

玄司图片按用户 2026-09-14 的明确选择单独保留版权。代码的商业许可不包含图片商业分发授权。使用者可通过软件形象菜单换成自己有相应权利的图片；向外分发产品时还需检查打包目录是否仍包含未获授权的默认图片。历史 NekoAI 素材保留原 MIT 声明，不改写为本项目原创。

### SenseVoice 模型

本次核对的 [FunASR Model License 1.1](https://raw.githubusercontent.com/modelscope/FunASR/main/MODEL_LICENSE) 包含来源标注、使用范围及其他附加条件，其中文条款还出现“仅作为参考和学习使用”的表述。不能把 SenseVoice 运行时代码的 Apache-2.0 等同于模型权重许可，也不能据此承诺任意商业场景均已获许可。

商业产品采用这组权重之前，应向上游确认目标使用及分发方式是否被允许，或替换为许可范围明确且符合产品需求的识别模型。本次仅记录边界，没有改变现有识别链路，没有宣称已获得额外商业授权。

### Qt、语音资源和 CUDA

Qt 的开源许可可以用于满足条款的商业分发，但实际组件可能适用不同许可。根据 [Qt 官方 LGPL 义务说明](https://www.qt.io/development/open-source-lgpl-obligations)，制作二进制包需要核对许可证与版权通知、对应源代码提供方式、用户替换或重新链接库的权利及其他适用条件；必要时选择相应商业许可。仅保留一个项目 LICENSE 不等于完成这些义务。

当前 Kokoro 配置使用模型包中的 `espeak-ng-data`。Kokoro 权重的 Apache-2.0 标签不等于 eSpeak NG 代码、数据及实际 sherpa 构建都能按 Apache 分发。本次已核对上游 GPL-3.0 文本，未完成具体数据文件和静态/动态链接关系的逐项审计；不能将此处写成“整包已获闭源商用许可”。默认朗读使用 Melo，安装脚本仍会下载可选 Kokoro 包。

NVIDIA CUDA 运行库是单独下载的第三方二进制组件，适用其实际发布包及 [CUDA EULA](https://docs.nvidia.com/cuda/eula/index.html) 中的许可和可再分发范围。llama.cpp 本身的 MIT 不覆盖 NVIDIA 组件。

## 下载与发布范围

运行库、权重、虚拟环境和用户 `data/` 不进入 Git；公开仓库提供下载脚本和 [固定清单](assets-manifest.json)。实际下载及解压时保留包内原有许可文件，不把这些组件重新标为项目 Apache-2.0。

Melo 历史 GitHub 发布包未提供作者 SHA256，清单里的值是首次 HTTPS 下载后计算并锁定的摘要，不是作者签名。其他摘要及版本由下载脚本和清单记录。AISHELL3 只在早期开发中测试过，未被当前应用采用，也不列入本次下载或发布内容。

历史说明：2026-09-13 本项目只在开发电脑集成，尚未发布；2026-09-14 用户授权发布到 `DesktopPetXuansi/Xuansi`，本文件据此更新许可范围与公开文档。实际推送和核验结果见 [开源发布验收](开源发布验收.md)，不将历史的本机安装记录当成商业发行验收。

2026-09-20 增量：默认语音输入改为上述在线 Paraformer，SenseVoice 保留为可选整句模式。在线模型的固定 URL、摘要见 `scripts/download_realtime.py`；未将权重上传仓库。本次使用已有 sherpa-onnx，不增加回声消除依赖。
