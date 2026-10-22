# 玄司官网真实客户端截图来源

- 发行源码：[`v0.8.0`](https://github.com/DesktopPetXuansi/Xuansi/tree/v0.8.0)，提交 `6bff0a38ddbf3dfc27dcd83281c999c64f8a769b`。
- 从 Git 发行 tag 隔离导出 `pet/`、`assets/` 与 `VERSION`，未修改发行代码。
- 通过该版本的 `Panel` 和 `AppearanceHub` 原生 Qt 窗口渲染，`QWidget.grab()` 保存 WebP。没有拼接、合成或重绘界面。
- 对话图只填写未发送草稿，不包含虚构 AI 回复；记忆内容为明确标注的演示草稿，未保存。形象图使用发行内置玄司 Live2D。
- 没有启动 AI 运行时、模型下载、联网、麦克风、屏幕观察、账号系统或反馈发送；未读取用户配置、真实聊天或密钥。
- 展示标注建议：**v0.8.0 客户端实拍；对话草稿和记忆为示例数据，未连接 AI 服务。**
- 渲染环境：Qt 6.11.2 / windows；统一逻辑窗口 880 × 660，实际图片尺寸如下。
- 复现：在仓库根目录运行 `.venv/Scripts/python.exe scripts/capture_website_media.py`。Windows 原生 Qt/Live2D 会短暂显示独立窗口，不主动抢占焦点；不支持 OpenGL 的 offscreen 平台不用于伪装成功预览。

| 文件 | 像素 | SHA-256 |
| --- | --- | --- |
| client-chat-v0.8.0.webp | 880 × 660 | `3aaa219fec3cd9a530124f5f5c3e02beca6b4c122496d00a0ff52a6adf84ca8b` |
| client-memory-v0.8.0.webp | 880 × 660 | `0068295ddb3fe5ad0cf7b0e2b02c038aac21cf170aacecb0644431da10830847` |
| client-appearance-v0.8.0.webp | 880 × 660 | `de29a39e09d73c629278d4ae0a171fc3a066b2303a751d507065fc32e674457d` |
