"""从 stdin 接收验收资源，发起真实客户端授权并验证 Go API、SDK 与离线资源。"""

import asyncio
import json
import logging
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pet.platform_api import PlatformClient  # noqa: E402
from pet.platform_auth import authorize  # noqa: E402
from pet.platform_resources import read_installed  # noqa: E402


class MemoryStore:
    """验收使用内存凭据，避免覆盖用户已保管的 Windows 官网授权。"""

    def __init__(self):
        self.tokens = None

    def read(self):
        return self.tokens

    def save(self, tokens):
        self.tokens = tokens

    def delete(self):
        self.tokens = None


def verify(payload):
    from PySide6.QtWidgets import QApplication, QWidget

    from pet.avatar import Avatar
    from pet.config import Settings, load_settings, save_settings
    from pet.live2d_session import configure_opengl_sharing

    store = MemoryStore()
    client = PlatformClient(payload["origin"], store)
    with tempfile.TemporaryDirectory(prefix="xuansi-real-api-") as directory:
        install_root = Path(directory) / "resources"

        async def download():
            def open_browser(url):
                # 仅发送给父进程，父进程消费后直接打开已登录的独立浏览器上下文。
                print(f"__QA_AUTHORIZE__{url}", flush=True)
                return True

            with patch("pet.platform_auth.webbrowser.open", open_browser):
                store.save(await authorize(payload["origin"]))
            print("客户端验收：真实 PKCE、随机回环监听与浏览器显式同意通过", flush=True)
            library = await client.request("GET", "/me/library")
            assert isinstance(library, list)
            for version in payload["versions"]:
                manifest = await client.install(version["resourceId"], version["resourceVersionId"], install_root)
                assert manifest["resourceVersionId"] == version["resourceVersionId"]
            import httpx

            previous = store.read()["access_token"]
            await client.logout()
            async with httpx.AsyncClient(timeout=10) as http:
                revoked = await http.get(payload["origin"] + "/api/v1/me/library",
                    headers={"Authorization": f"Bearer {previous}"})
                assert revoked.status_code == 401
            assert store.read() is None
            print("客户端验收：真实客户端注销与服务端即时撤销通过", flush=True)

        asyncio.run(download())
        print("客户端验收：真实 API 授权、流式下载、清单摘要和原子安装通过")
        by_kind = {item["kind"]: item for item in payload["versions"]}
        model = by_kind["MODEL"]["resourceVersionId"]
        motion = by_kind["MOTION"]["resourceVersionId"]
        expression = by_kind["EXPRESSION"]["resourceVersionId"]
        configure_opengl_sharing()
        application = QApplication.instance() or QApplication([])
        window = QWidget()
        window.setWindowTitle("玄司资源平台本地验收")
        window.resize(400, 460)
        avatar = Avatar(300, parent=window)
        window.show()

        def events(seconds=0.25):
            finish = time.monotonic() + seconds
            while time.monotonic() < finish:
                application.processEvents()
                time.sleep(0.01)

        try:
            events()
            avatar.select_platform_model(model, read_installed(model, install_root))
            assert avatar._platform_model_version == model and avatar._live2d_active
            assert not avatar.available_motions, "外部模型不应公布玄司专用动作"
            avatar.apply_platform_action(motion, read_installed(motion, install_root))
            assert not avatar._live2d_model.IsMotionFinished(), "动作必须实际启动 SDK"
            events()
            avatar.apply_platform_action(expression, read_installed(expression, install_root))
            events()
            assert avatar._platform_expression
            assert not avatar.grabFramebuffer().isNull()
            screenshot = ROOT / "web/.runtime/screenshots/native-resource.png"
            assert window.grab().save(str(screenshot))
            print("客户端验收：原生模型切换、真实动作播放、表情应用与截图通过")
            settings_path = Path(directory) / "settings.json"
            save_settings(replace(Settings(), platform_url=payload["origin"],
                platform_model_version=model, platform_expression_version=expression), settings_path)
            settings = load_settings(settings_path)
            avatar.select_platform_model(settings.platform_model_version,
                read_installed(settings.platform_model_version, install_root))
            avatar.apply_platform_action(settings.platform_expression_version,
                read_installed(settings.platform_expression_version, install_root))
            assert avatar._platform_expression
            print("客户端验收：本地配置恢复与离线重新校验/应用通过")
        finally:
            avatar.clock.stop()
            avatar.render_clock.stop()
            avatar._release_live2d()
            window.close()
            application.processEvents()
            store.delete()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        verify(json.load(sys.stdin))
    except Exception as exc:
        # 外部库异常可能带签名 URL；失败输出仅保留异常类型。
        print(f"客户端验收失败：{type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
