# 玄司官网真实客户端截图来源

- 发行源码：[`v0.8.0`](https://github.com/DesktopPetXuansi/Xuansi/tree/v0.8.0)，提交 `6bff0a38ddbf3dfc27dcd83281c999c64f8a769b`。
- 从 Git 发行 tag 隔离导出 `pet/`、`assets/` 与 `VERSION`，未修改发行代码。
- 通过该版本的 `Panel` 和 `AppearanceHub` 原生 Qt 窗口渲染，`QWidget.grab()` 保存无损 PNG。没有拼接、合成或伪造界面。
- 使用 `QT_SCALE_FACTOR=3` 原生高 DPI 绘制文字与控件，像素为 2640×1980；不是对旧 880×660 位图插值放大。网页直接展示 PNG，不经过有损转码。
- 对话图只填写未发送草稿，不包含虚构 AI 回复；记忆内容为明确标注的演示草稿，未保存。形象图使用发行内置玄司 Live2D。
- 没有启动 AI 运行时、模型下载、联网、麦克风、屏幕观察、账号系统或反馈发送；未读取用户配置、真实聊天或密钥。
- 展示标注建议：**v0.8.0 客户端实拍；对话草稿和记忆为示例数据，未连接 AI 服务。**
- 渲染环境：Qt 6.11.2 / windows；统一逻辑窗口 880 × 660，设备像素比为 3，实际图片尺寸如下。
- 旧 WebP 路径保留供已有链接使用；当前首页采用下列无损 PNG。
- 复现：在仓库根目录运行 `.venv/Scripts/python.exe scripts/capture_website_media.py`。Windows 原生 Qt/Live2D 会短暂显示独立窗口，不主动抢占焦点；不支持 OpenGL 的 offscreen 平台不用于伪装成功预览。

| 文件 | 像素 | SHA-256 |
| --- | --- | --- |
| client-chat-v0.8.0-3x.png | 2640 × 1980 | `3268a14511636b1d4a91b7aabd06e66f7911d0041ab780b18ebb340bd1230172` |
| client-memory-v0.8.0-3x.png | 2640 × 1980 | `a1ff96171d002f819f759c86ab0cddf1a430ec49e76e7d8fa9b0fd37b6405047` |
| client-appearance-v0.8.0-3x.png | 2640 × 1980 | `0ac0fa64200b56aba5320ae2c7493f6ea6a268c7a516d28dfa90deb292c7e86d` |
