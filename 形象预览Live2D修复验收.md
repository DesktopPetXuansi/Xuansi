# 形象预览 Live2D 修复验收

日期：2026-10-07。直接依据用户反馈“更换桌宠形象”页面仍播放旧跳动动画，以及随后批准采用与桌宠相同的 Live2D 预览并增加眨眼按钮。范围仅为本桌宠的形象预览、共享绘制资源及相应检查和文档。

## 1. 问题与修复

旧 `AppearancePreview` 只调用 `build_frames(224)`，用默认 PNG 生成 8 帧轻微位移，以 180 毫秒间隔循环。桌宠已经使用 Live2D，预览页却没有接入模型，因此看不到桌面上的眨眼、视线跟随及头发衣摆动作。修改前真实 Qt 检查报出“默认形象预览仍未接入 Live2D”，失败报告保留。

现在默认预览使用嵌入式 `Avatar`，沿用桌宠的绘制、参数驱动和已绑定动作。窗口提供“预览眨眼”按钮；动作只影响独立的预览模型，不应用候选、不产生配置草稿、不触发桌宠动作。导入静态图保留既有轻微动作，动图继续使用原帧序与时长，二者均禁用 Live2D 眨眼。

模型加载失败时显示明确提示并禁用动作按钮；关闭后重新打开可以重试。预览不创建桌面气泡、不加载久置拔刀姿态；隐藏时停止计时器并释放模型。默认 PNG 缓存由预览渲染器共享，避免重复生成。

## 2. 共享资源与恢复

Cubism 核心和着色器属于应用共享资源，不能由任一窗口单独销毁。启动入口在创建 `QApplication` 前设置 OpenGL 上下文共享；`Live2DSession` 登记模型持有者，关闭预览只归还该窗口的模型。

最后一个模型关闭时释放公共着色器，保留应用核心以支持再次打开；应用退出时先销毁全部模型，再释放核心。初始化中途失败也回收已分配模型。预览 GL 控件在顶层窗口显示前加入布局，并保留至窗口销毁，避免动态加入控件导致原生窗口重建和首次显示重入、重复创建模型。

依据为本机 `live2d-py 0.8.0.9` 包源码、上游 [多窗口示例](https://github.com/EasyLive2D/live2d-py/blob/main/examples/main_pyqt5_multi_win.py)、[初始化及公共释放实现](https://github.com/EasyLive2D/live2d-py/blob/main/Wrapper/Init.cpp) 和 [Qt 上下文共享与资源释放文档](https://doc.qt.io/qt-6/qopenglwidget.html#context-sharing)。没有增加或升级运行依赖。

## 3. 实际检查

| 检查 | 结果 |
| --- | --- |
| 完整自动测试 | 238 项通过，27.52 秒；包含 3 项共享资源生命周期回归 |
| 真实 Qt / Live2D 动态预览 | 37 项通过：真实画面变化、发丝衣摆推进、模拟鼠标视线、眼睛实际闭合及恢复、双底色、按钮和草稿隔离 |
| 关闭、重开、加载失败恢复 | 包含在上述 37 项；模型数符合预期，无首次显示重复登记，关闭后桌宠仍能绘制 |
| 静态图、动图、恢复默认 | 包含在上述 37 项；临时导入、80/160 毫秒帧时长及按钮状态通过 |
| 既有形象业务流程 | 32 项通过：保存失败、原图删除、透明帧清屏和穿透、未保存表单保留、图标同步、恢复默认及迟到导入隔离 |
| Ruff 与差异空白检查 | 通过 |
| 当前文档本地引用 | 111 个引用均存在 |
| 原生画面抽查 | 查看本窗口截图，角色、双底色、动作提示及按钮完整显示，无文字裁切 |
| 独立只读审阅 | 无阻塞问题；额外确认初始隐藏及停止后的预览计时器均未运行 |

真实窗口测试使用隔离的 Qt 应用、本项目默认角色和临时人工图片，不运行语言模型、不启用真实麦克风、不采集用户屏幕、不更改用户设置或记忆。错误恢复检查主动加入不存在的参数，日志中的该项加载失败是验收输入；原始问题和检查脚本中间失败记录均保留。

检查命令：

```powershell
& .venv/Scripts/python.exe -X utf8 -m pytest -q
& .venv/Scripts/python.exe -X utf8 scripts/verify_appearance_preview.py
& .venv/Scripts/python.exe -X utf8 scripts/verify_appearance_menu.py
& .venv/Scripts/python.exe -m ruff check pet tests scripts
```

本机证据在 `data/verification/`：`appearance-preview-before.json`、`appearance-preview-final.json`、`appearance-preview-final.log`、`appearance-preview-final.png`、`appearance-preview-unit-final.log`、`appearance-menu-report.json` 和 `appearance-menu-preview-regression.log`。证据目录不加入公开源码。

## 4. 版本与使用边界

当前修复在源码分支 `codex/live2d-appearance-preview`，基础提交为 `6acbf4d`。已发布的 `v0.5.3` 标签、安装器和 `VERSION` 没有更新；本次不是安装包发布验收。运行中的旧源码桌宠仍需由用户从托盘退出，再重新启动才能加载修复。

只有默认玄司具有本项目既有 Live2D 绑定，自定义 PNG 或动图不会自动获得眨眼、口型或骨骼能力。本次在现有 Windows / NVIDIA / Qt 环境验证，不扩展为其他硬件或平台已验收。

## 5. 本轮投入

可验证的协作记录为北京时间 2026-10-07 07:28:27 至 07:47:15，约 19 分钟，覆盖实现、测试、记录和独立审阅，包含测试及审阅等待。本地提交收尾另计；该经过时间不作为精确主动工时。
