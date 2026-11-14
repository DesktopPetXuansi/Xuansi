# 商店 MSIX 容器构建

## 开发载荷准备

下面的工具仅用于本地开发验证，不联网、不安装、不导入证书，也不授予任何组件发行权。输入 Python 运行时和依赖必须由操作者先取得并核实；依赖版本需与 `requirements.lock.txt` 一致。输出必须是输入目录之外、尚不存在的新目录。

```powershell
.\.venv\Scripts\python.exe -B scripts/stage_store_payload.py `
  --source '<源码快照>' `
  --python-runtime '<独立 Python 3.13 运行时目录>' `
  --dependencies '<已安装锁定依赖的 site-packages 目录>' `
  --output '<全新的临时载荷目录>'

.\.venv\Scripts\python.exe -B scripts/finish_store_payload.py `
  --payload '<上述临时载荷目录>' `
  --launcher-source 'installer/store/StoreLauncher.cs' `
  --compiler '<Windows .NET Framework x64 csc.exe>'
```

暂存清单会将运行时来源与发行许可标记为未核实；它不是正式发行产物。启动器从载荷启动独立 Python，首次启动时由用户选择并确认资源，设置和推理运行时写入用户可写目录。测试选择取消后仍会保留已经下载的文件，以便后续重试。

## 未签名容器构建

`scripts/build_store_package.py` 从已经暂存的载荷生成未签名 MSIX。它不安装程序、不导入证书，也不提交微软商店。此阶段只证明容器结构和内容映射能由 MakeAppx 校验，不能证明应用可以启动、卸载后保留数据或通过商店审核。

调用时必须提供 Partner Center 的正式包名称、发布者和发布者显示名称，以及四段包版本（最后一段为 `0`）。实际入口 `.exe`、50×50 商店图标、44×44 图标和150×150 图标应已存在于载荷中，以相对路径传入。全信任桌面清单声明 `Windows.FullTrustApplication`、`runFullTrust`、Windows 10 1809 x64；入口参数和首次启动流程由实际启动器负责。

```powershell
.\.venv\Scripts\python.exe scripts/build_store_package.py `
  --payload '<已核实的暂存载荷目录>' `
  --output 'dist/<本次新产物名称>.msix' `
  --makeappx '<Windows SDK 中的 MakeAppx.exe>' `
  --identity '<Partner Center 的 Package/Identity/Name>' `
  --publisher '<Partner Center 的 Package/Identity/Publisher>' `
  --publisher-display-name '<Partner Center 的 PublisherDisplayName>' `
  --version '<本次四段商店包版本>' `
  --executable '<载荷内入口.exe>' `
  --display-name '<预留的应用显示名称>' `
  --store-logo '<载荷内50像素图标.png>' `
  --small-logo '<载荷内44像素图标.png>' `
  --large-logo '<载荷内150像素图标.png>'
```

载荷必须单独暂存并核实内容，不能直接使用开发工作目录；工具拒绝顶层 `data`、`models`、`.venv`、`.git`、`.env*` 和已有 MSIX 元数据。符号链接与目录联接也会被拒绝；这不代替逐项核对嵌套文件及其许可。输入文件保持原样，已有输出永不覆盖；输出位于仓库时只能使用 `build/` 或 `dist/`。Windows 上构建产物通过同卷重命名发布；其他系统上的替身测试需要硬链接支持。

Python、运行依赖、角色素材和模型各自的发行授权，需要在准备真实载荷时核实；工具不会推断任何新增授权。测试中的 `LocalDevelopment.*` 仅用于临时、未安装的容器，不是玄司的正式商店身份。

依据：[微软手工生成 MSIX 组件](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-manual-conversion)、[MakeAppx 工具说明](https://learn.microsoft.com/en-us/windows/msix/package/create-app-package-with-makeappx-tool)。MakeAppx 的语义验证有限，不能替代真实安装、Windows App Certification Kit 与微软商店审核。
