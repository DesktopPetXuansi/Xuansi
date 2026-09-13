# 上游来源与许可记录

核对日期：2026-09-13。运行时、权重和虚拟环境不进入本项目 Git 历史；保留上游原名与许可文件。

| 组件 | 来源与版本 | 许可/说明 |
| --- | --- | --- |
| 猫精灵、图标、动画定义 | [nucket/NekoAI](https://github.com/nucket/NekoAI)，提交 `6c3f1235063ee0748fc710977b0c4a93aa76bdea` | MIT；原文在 `assets/neko/LICENSE`，上游源码在 `upstream-nekoai` |
| 图文基础模型 | [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) | Apache-2.0 |
| GGUF 及视觉组件 | [unsloth/Qwen3.5-4B-GGUF](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF)，提交 `e87f176479d0855a907a41277aca2f8ee7a09523` | 基于上述模型的转换；按 HF LFS 摘要校验 |
| 推理引擎 | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)，b10930 Windows CUDA 12.4 | MIT；CUDA 运行库为 NVIDIA 发布组件，不能把整个二进制包统称 MIT |
| 语音识别权重 | [FunAudioLLM/SenseVoiceSmall](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)，sherpa-onnx int8 2025-09-09 转换 | 模型卡链接的是 [FunASR Model License](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE)，并非 Apache-2.0；本机另存许可快照 |
| 默认语音权重 | [MyShell.ai/MeloTTS](https://github.com/myshell-ai/MeloTTS)，sherpa `vits-melo-tts-zh_en` | MIT；压缩包自带 LICENSE。44100Hz，中英，1 音色 |
| 可选语音权重 | [hexgrad/Kokoro-82M-v1.1-zh](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)，sherpa int8 multi-lang v1_1 | 模型 Apache-2.0；转换包自带 LICENSE，含额外语音处理资源，保留原包 |
| 语音运行时/转换 | [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)，1.13.8 | Apache-2.0；预训练权重分别按各自许可 |
| 界面 | [Qt for Python / PySide6](https://doc.qt.io/qtforpython-6/)，6.11.2 Essentials | LGPL-3.0 / GPL-3.0 / 商业许可体系；本机动态使用 pip 包 |
| Windows 音频会话接口 | [AndreMiras/pycaw](https://github.com/AndreMiras/pycaw)，20251023 | MIT；只使用查询和通知接口 |
| Windows COM 桥接 | [enthought/comtypes](https://github.com/enthought/comtypes)，1.4.16 | MIT；本机 pip 包保留许可 |

Python 依赖准确版本由 `requirements.lock.txt` 锁定。公开下载清单见 `assets-manifest.json`。Melo 历史 GitHub 发布包未提供作者摘要，清单中的 SHA256 是本次首次 HTTPS 下载后计算并锁定的摘要；不把它描述为作者签名。

AISHELL3 是开发时测试过但未采用的语音模型，旧下载文件保留在 D 盘，默认应用不会加载；失败样例保留在本地验收目录。未向 GitHub 发布本项目或上传本机数据。
