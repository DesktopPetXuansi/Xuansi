# 玄司 Live2D 绑定素材

原立绘为上一级 [front.png](../front.png)，1024 × 1536。原图文件未改写；本次拆层输入的 SHA256 为 `32d772af97c79d15d086a2895c58beec397d2667bedd4af53936b7cc12138d34`。本目录素材继续遵循 [玄司图片声明](../LICENSE)。

## 文件

- `xuansi-layers.psd` 和 `layers/*.png`：可在图像编辑器检查的八个分层素材（身体、头部底图、左右眼白与眼球、闭嘴、张嘴）。`layers.json` 记录层坐标、原图哈希和脸部透明孔洞修复像素数。
- `xuansi.cmo3`：Cubism Editor 可继续编辑的工程。
- `xuansi.moc3`、`xuansi.model3.json`、`xuansi.cdi3.json`、`xuansi.1024/texture_00.png`：运行时模型、参数名称和图集。
- `blink-mouth-reference.png`：闭眼与张嘴补绘参考；脚本只提取眼睛和嘴部的小区域，没有用生成图替换整张原立绘。
- `neutral-preview.png`、`blink-talk-preview.png`：组装层的静态检查图；不是运行时截图。

## 当前绑定

| 参数 | 行为 |
| --- | --- |
| `ParamEyeBallX`、`ParamEyeBallY` | 根据鼠标相对桌宠的位置平滑移动视线 |
| `ParamEyeLOpen`、`ParamEyeROpen` | Cubism 自动眨眼；休眠状态强制闭眼 |
| `ParamMouthOpenY` | 根据 TTS 正在播放的音频响度开合，停止、取消、静音和休眠时归零 |
| `ParamHairBack` | 后发尾部局部网格在 -1 到 +1 间往返摆动 |
| `ParamBodyAngleX` | 衣摆边缘局部网格在 -10 到 +10 间往返摆动；参数错相，不带动头脸、手臂和靴子 |

2026-09-28 根据“瞳孔移动不明显”的反馈调整：眼球关键形从横向 ±7、纵向 ±5 原图像素，扩大为 ±18、±10；中立位置和眨眼不透明度保留。鼠标按眼睛到桌宠所在屏幕边缘的距离映射，越过该屏幕后停留在对应视线方向，不因其他显示器扩大映射范围。当前 160/384 像素高度均检查了九个方向；只在单屏常规 DPI 设备上运行，跨屏与混合 DPI 尚无实机验收。实现依据为 [官方 X/Y 关键形说明](https://docs.live2d.com/en/cubism-editor-manual/keyform-xydirection/)。

自动眨眼还要求 `xuansi.model3.json` 的 `Groups` 包含 `Target: Parameter`、`Name: EyeBlink`，并在 `Ids` 中列出左右眼参数。仅有参数和 `SetAutoBlinkEnable(True)` 不会自动创建这个映射。重新从 Cubism 导出时，须配置编辑器的眨眼参数并检查此组仍在；参考 [官方自动眨眼说明](https://docs.live2d.com/en/cubism-sdk-manual/autoeyeblink/)。

2026-09-27 连续播放核验：修复前刷新定时器运行，但 10 秒内眼睛开合值一直为 1；补齐此组后，真实 OpenGL 预览中的开合值覆盖 0 到 1，并出现可见闭眼帧。逐项参数检查也确认视线和口型改变画面，而转头、倾斜、呼吸参数没有对应变形；参数数量不代表已完成的绑定数量。

2026-09-29 摆动核验：保留合并的头部和身体图层，只在头部网格的 23 个后发点、身体网格的 19 个衣摆点加入 -1／0／+1 关键形。单模型 OpenGL 预览中，头发和衣摆极值都可见；衣摆极值没有拉动手臂或靴子。应用每 2.8 秒完成一个周期，并在 30 FPS 绘制帧中错相驱动两个参数；不启用独立物理模拟或新增运行依赖。

2026-09-29 补充修复：按实际 120 × 160 窗口复查发现，原 PNG 轮廓掩码会裁切超出轮廓的抗锯齿发丝。Live2D 点击区域现按窗口高度增加 3.125% 的边缘缓冲（160px 高度下为 5px）；实际尺寸预览中，窗口掩码外模型像素从摆动极值时的约 2100–2400 降至 55–120。原 PNG 形状和模型纹理保持不变。对应自动化测试仍为 `tests/test_avatar_sway.py`。

本模型是原单图拆出的基础绑定：没有逐束发丝、手臂和衣物独立图层；头发与衣摆使用现有 ArtMesh 的局部网格变形，不是逐束头发或 Cubism 物理模拟。没有头部转动、身体呼吸或摄像头面捕。张嘴补绘和脸部局部透明修复可能不与原图逐像素相同；原始 `front.png` 保持原样。`scripts/prepare_xuansi_live2d.py` 仅针对原图 1024 × 1536 的坐标，尺寸或立绘变化后需重新校准。要重建 PSD，请在项目环境安装 `requirements-rigging.lock.txt` 后运行该脚本；此可选依赖不用于桌宠运行。

Editor 使用 Cubism 5.3.04，模型目标版本选为 SDK 5.0，使当前绑定数据能被锁定的运行时加载。更换导出目标前，需按 [Cubism 官方目标版本说明](https://docs.live2d.com/en/cubism-editor-manual/target-version-selection/) 和运行时兼容性重新验证。工程与运行时模型均保留在本目录；构建应用前还需核对运行库中 Cubism Core 的适用许可，详见根目录 [第三方许可记录](../../../THIRD_PARTY.md)。
