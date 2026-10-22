"""从隔离发行源码采集真实官网截图，不读取用户配置、不启动 AI 或麦克风。"""

import argparse
import asyncio
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "web/frontend/public/product"
RELEASE = "v0.8.0"
LOGICAL_SIZE = (880, 660)
CAPTURE_SCALE = 3
LOG = logging.getLogger(__name__)


async def git_output(*arguments):
    """异步读取 Git 对象，始终保留当前工作树和其他修改。"""
    process = await asyncio.create_subprocess_exec(
        "git", *arguments, cwd=ROOT,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError(stderr.decode("utf-8", errors="replace"))
    return stdout


def deny_network(*_arguments, **_keywords):
    """采集时连接任何网络都视为错误，而非静默访问在线服务。"""
    raise RuntimeError("官网截图采集禁止联网")


def render(source, output):
    """使用发行源码原生 Qt 控件，所有样例仅在内存中，不连接运行时。"""
    sys.path.insert(0, str(source))
    from PySide6.QtCore import Qt, QTimer, qVersion
    from PySide6.QtWidgets import QApplication
    from pet.appearance_hub import AppearanceHub
    from pet.config import Settings
    from pet.live2d_session import configure_opengl_sharing
    from pet.panel import Panel

    assert (source / "VERSION").read_text(encoding="utf-8").strip() == RELEASE[1:]
    configure_opengl_sharing()
    application = QApplication([])
    application.setQuitOnLastWindowClosed(False)
    panel = Panel(replace(Settings(), observe=False, speak_replies=False))
    panel.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    # 固定逻辑窗口，按 Qt 高 DPI 原生绘制；不把旧位图插值放大。
    panel.setFixedSize(*LOGICAL_SIZE)
    # 使用未发送草稿和未保存记忆，避免伪装成真实模型的回复或用户聊天。
    panel.input.setText("今天想专心读完一章书，陪我一起开始吧。")
    panel.memory.setPlainText(
        "【官网演示用示例，未保存】\n\n"
        "称呼：小玄\n"
        "偏好：喜欢简短自然的中文回复。\n"
        "陪伴方式：工作和阅读时安静陪伴，主动询问时再交流。\n\n"
        "这里可以手动编辑、保存或清空长期记忆。"
    )
    appearance = AppearanceHub(panel)
    panel.mount_section("appearance", appearance, on_open=lambda: appearance.set_current(appearance.current))
    pages = iter(("chat", "memory", "appearance"))
    records, errors = [], []

    def advance():
        key = next(pages, None)
        if key is None:
            application.quit()
            return
        try:
            # 不调用激活窗口的 open_section；主事件循环绘制原生内容后直接 grab。
            panel.navigation.select(key)
            panel.show()
            QTimer.singleShot(750, lambda: capture(key))
        except Exception as error:
            errors.append(error)
            application.quit()

    def capture(key):
        try:
            if key == "appearance":
                renderer = appearance.preview.renderer
                assert renderer._live2d_active and not renderer._live2d_failed, "Live2D 预览未成功，拒绝发布空截图"
            filename = f"client-{key}-{RELEASE}-3x.png"
            image = panel.grab().toImage()
            expected_size = tuple(size * CAPTURE_SCALE for size in LOGICAL_SIZE)
            assert (image.width(), image.height()) == expected_size, "未得到原生 3 倍像素截图"
            assert image.devicePixelRatio() == CAPTURE_SCALE, "Qt 高 DPI 倍率不正确"
            # PNG 保留文字与细线的原始像素，避免 WebP 有损编码及二次转码。
            assert image.save(str(output / filename), "PNG"), "无损截图保存失败"
            record = {"file": filename, "width": image.width(), "height": image.height(),
                      "devicePixelRatio": image.devicePixelRatio()}
            records.append(record)
            LOG.info("已采集发行界面 %s", record)
            QTimer.singleShot(0, advance)
        except Exception as error:
            errors.append(error)
            application.quit()

    QTimer.singleShot(0, advance)
    application.exec()
    appearance.preview.stop()
    panel.hide()
    if errors:
        raise errors[0]
    (output / "capture.json").write_text(
        json.dumps({"qt": qVersion(), "platform": application.platformName(), "images": records},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


async def prepare(output):
    output.mkdir(parents=True, exist_ok=True)
    commit = (await git_output("rev-parse", RELEASE)).decode().strip()
    archive = await git_output("archive", "--format=zip", RELEASE, "pet", "assets", "VERSION")
    # 只导出被 Git 跟踪的发行素材，不复制 data、密钥、账号或当前开发代码。
    with tempfile.TemporaryDirectory(prefix="xuansi-website-release-") as directory:
        source = Path(directory)
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            bundle.extractall(source)
        environment = dict(os.environ, QT_SCALE_FACTOR=str(CAPTURE_SCALE), QT_AUTO_SCREEN_SCALE_FACTOR="0",
                           PYTHONIOENCODING="utf-8")
        environment.pop("QT_QPA_PLATFORM", None)
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).resolve()), "--render", str(source), "--output", str(output),
            cwd=source, env=environment,
        )
        if await process.wait():
            raise RuntimeError("发行截图渲染失败，请查看上述 Qt 日志")
    report = json.loads((output / "capture.json").read_text(encoding="utf-8"))
    (output / "capture.json").unlink()  # 临时进程报告不作为官网公共资源发布。
    entries = []
    for image in report["images"]:
        path = output / image["file"]
        digest = await asyncio.to_thread(lambda asset=path: hashlib.sha256(asset.read_bytes()).hexdigest())
        entries.append(f"| {image['file']} | {image['width']} × {image['height']} | `{digest}` |")
    provenance = (
        "# 玄司官网真实客户端截图来源\n\n"
        f"- 发行源码：[`{RELEASE}`](https://github.com/DesktopPetXuansi/Xuansi/tree/{RELEASE})，提交 `{commit}`。\n"
        "- 从 Git 发行 tag 隔离导出 `pet/`、`assets/` 与 `VERSION`，未修改发行代码。\n"
        "- 通过该版本的 `Panel` 和 `AppearanceHub` 原生 Qt 窗口渲染，`QWidget.grab()` 保存无损 PNG。没有拼接、合成或伪造界面。\n"
        "- 使用 `QT_SCALE_FACTOR=3` 原生高 DPI 绘制文字与控件，像素为 2640×1980；不是对旧 880×660 位图插值放大。网页直接展示 PNG，不经过有损转码。\n"
        "- 对话图只填写未发送草稿，不包含虚构 AI 回复；记忆内容为明确标注的演示草稿，未保存。形象图使用发行内置玄司 Live2D。\n"
        "- 没有启动 AI 运行时、模型下载、联网、麦克风、屏幕观察、账号系统或反馈发送；未读取用户配置、真实聊天或密钥。\n"
        "- 展示标注建议：**v0.8.0 客户端实拍；对话草稿和记忆为示例数据，未连接 AI 服务。**\n"
        f"- 渲染环境：Qt {report['qt']} / {report['platform']}；统一逻辑窗口 880 × 660，设备像素比为 3，实际图片尺寸如下。\n"
        "- 旧 WebP 路径保留供已有链接使用；当前首页采用下列无损 PNG。\n"
        "- 复现：在仓库根目录运行 `.venv/Scripts/python.exe scripts/capture_website_media.py`。Windows 原生 Qt/Live2D 会短暂显示独立窗口，不主动抢占焦点；不支持 OpenGL 的 offscreen 平台不用于伪装成功预览。\n\n"
        "| 文件 | 像素 | SHA-256 |\n| --- | --- | --- |\n" + "\n".join(entries) + "\n"
    )
    await asyncio.to_thread((output / "provenance.md").write_text, provenance, encoding="utf-8")
    LOG.info("真实发行截图已就绪 source=%s", commit)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if arguments.render:
        with patch("socket.socket.connect", deny_network), patch("socket.create_connection", deny_network):
            render(arguments.render, arguments.output)
    else:
        asyncio.run(prepare(arguments.output.resolve()))


if __name__ == "__main__":
    main()
