# 玄司 Live2D 制作规格

运行说明核对日期：2026-10-11。本文集中维护现行绑定、驱动与预览边界；素材制作来源和原始参数检查保存在 [绑定素材说明](../归档/Live2D与形象/素材制作记录.md#record-a4f613e5)。版本状态见 [文档索引](../README.md)，下方历史验收未在本轮重新执行。

## 目标与实现

在现有玄司桌宠中加入基础 Live2D 动态，同时保留原聊天、语音、记忆、透明窗口和自定义图片能力。用户选择使用原有玄司立绘，并授权用本机脚本拆层、组装 PSD。

以 `assets/xuansi/front.png` 为源图制作 8 个绑定图层、PSD、可编辑 Cubism 工程和运行时模型。原 PNG 未修改，SHA256 为 `32d772af97c79d15d086a2895c58beec397d2667bedd4af53936b7cc12138d34`。模型以 Cubism 5.3.04 建立，导出目标为 SDK 5.0。

## 运行时行为

- 默认玄司加载 `assets/xuansi/rigging/xuansi.model3.json`；加载失败时回退原 PNG 动画，不阻断桌宠。
- 双眼随机眨动，休眠时闭眼；眼球平滑跟随鼠标位置。
- TTS 播放时，每 50 ms 取一段实际输出波形的 RMS 幅度驱动嘴部；音频停止、取消、静音或休眠时闭嘴。
- 头发由发根、发中、发梢三段阻尼弹簧链驱动，基础风向周期约 2.8 秒，以 60 Hz 小步积分；衣摆独立周期约 4.2 秒，错相摆动。复用每个角色现有约 30 FPS 绘制计时器，不使用 Cubism 物理模拟或动画线程。
- 用户导入的 PNG、JPG、BMP 和动图仍走原有自定义形象流程。
- Live2D 绘制经 `QOpenGLWidget.paintGL` 完成；隐藏时停止刷新，继续使用透明无焦点窗口和原点击、拖动行为。
- 当前源码的形象窗口嵌入独立 `Avatar`，默认候选可自动眨眼、跟随视线、摆动发丝衣摆，并提供“预览眨眼”按钮；预览不显示气泡、不接入 TTS 口型，也不播放久置拔刀。该增量从 0.5.4 纳入安装包，见 [发布验收](../归档/发布与安装/验收/安装包0.5.4发布验收.md)。
- 桌宠和预览共享 OpenGL 上下文、Cubism 核心与公共着色器，各自持有模型；关闭预览释放自身模型，最后一个模型关闭后释放公共着色器，应用退出才释放核心。加载失败回退 PNG，关闭重开可以重试，动作按钮按实际能力禁用。
- 桌宠久置拔刀使用预制全身透明姿态帧；姿态显示时清空 GL 缓冲并暂停底层模型更新和绘制，动作结束后恢复，避免完整角色轮廓叠加。

## 可编辑文件与绑定参数

- `assets/xuansi/rigging/xuansi-layers.psd`、`layers/*.png`：眼睛、嘴部、头部和身体的素材层。
- `assets/xuansi/rigging/xuansi.cmo3`：Cubism 工程。
- `assets/xuansi/rigging/xuansi.moc3`、`xuansi.model3.json`、`xuansi.cdi3.json`、`xuansi.1024/texture_00.png`：运行时模型、参数和纹理。

| 实际参数名 | 已接入行为 |
| --- | --- |
| `ParamEyeBallX`、`ParamEyeBallY` | 按角色所在显示器边界平滑映射鼠标视线 |
| `ParamEyeLOpen`、`ParamEyeROpen` | 自动眨眼、一次性眨眼及休眠闭眼 |
| `ParamMouthOpenY` | 播放响度口型，停止、取消、静音或休眠归零 |
| `ParamHairFront`、`ParamHairSide`、`ParamHairBack` | 发根、发中、发梢的弹簧链摆动 |
| `ParamBodyAngleX` | 衣摆局部网格摆动，不驱动整身体转动 |

自动眨眼还要求 `xuansi.model3.json` 中的 `EyeBlink` 参数组包含左右眼开合 ID；仅存在参数或启用自动眨眼不足以证明绑定可用。当前 [动作能力](../../pet/avatar_motion.py) 由 `ARM_RAISE_BINDING_VERIFIED=False` 禁用原生抬手，只开放 `blink`。未跟踪的个人 Cubism 工程不作为运行时模型或已交付动作的证据。

久置拔刀要求持续五分钟满足默认 Live2D、idle、桌面可用、无忙碌任务和无收音等资格，并且没有系统键鼠输入；资格中断重置计时。实现与姿态文件见 [久置拔刀说明](#久置拔刀姿态)。

单张立绘不足以还原全套角色结构。本版没有逐束发丝、衣物和手臂独立分层；头发与衣摆通过合并 ArtMesh 的局部网格关键形摆动，不是 Cubism 物理模拟。当前没有头部转动、身体呼吸或摄像头面捕；口型是响度驱动，不是音素级口型。绑定只针对当前 1024 × 1536 立绘坐标。

历史关键形、连续播放、像素与测试记录见 [形象演进验收](../归档/Live2D与形象/形象演进验收.md) 和 [素材制作记录](../归档/Live2D与形象/素材制作记录.md)。

## 官方与上游参考

- [Cubism 导出和版本选择](https://docs.live2d.com/en/cubism-editor-manual/target-version-selection/)
- [Cubism Core 官方说明与许可入口](https://docs.live2d.com/cubism-sdk-manual/cubism-core/)
- [live2d-py 上游说明](https://github.com/EasyLive2D/live2d-py)
- [Qt `QOpenGLWidget` 官方文档](https://doc.qt.io/qt-6/qopenglwidget.html)

## 久置拔刀姿态

素材位置：[assets/xuansi/idle-blade/](../../assets/xuansi/idle-blade/)。下文目录和文件名均指该素材目录，图片和制作脚本保持原位。


这组透明 PNG 用于默认 Live2D 玄司的单次久置待机动作。`reach.png` 抬手够刀柄，`grip.png` 握住刀柄，`draw-half.png` 半拔，`drawn.png` 展示完整拔出的长刀；播放时按相反顺序收刀。它不属于对话模型可调用的原生抬手动作。

计时由 [idle_action.py](../../pet/idle_action.py) 与 [app.py](../../pet/app.py) 的系统最后输入时间驱动：持续五分钟无键鼠输入且满足默认 Live2D、idle、桌面可用、无忙碌任务和无收音等资格后才播放；资格中断重置。系统输入检测只读取时间戳，不读取键盘正文。

现有 PSD 的身体层合并了双臂。运行时使用全身透明姿态，可以避免单独叠加手臂时留下原手臂重影。姿态显示时清空 GL 缓冲，只显示姿态帧，暂停底层 Live2D 参数更新和绘制；动作结束或用户有键鼠输入后淡出姿态并恢复模型。默认尺寸下四帧缓存约 0.29 MiB，姿态素材在初始化、尺寸变化或形象重新加载时预读并缩放，动画播放过程中不逐帧读盘。

暂停底层绘制的分支见 [Live2D 绘制](../../pet/avatar_live2d.py)，姿态与淡出见 [拔刀实现](../../pet/avatar_idle_blade.py)。形象预览不加载拔刀姿态，不会因预览窗口久置自动播放此动作。历史更正见 [素材制作记录](../归档/Live2D与形象/素材制作记录.md)。

姿态图基于 `assets/xuansi/front.png` 制作，作为玄司美术素材的衍生图受 `assets/xuansi/LICENSE` 所列权利约束。源 PNG、Live2D PSD、网格和纹理均保持不变。
