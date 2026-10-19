"""原生形象流程验收；仅截取本程序控件，网络和配置写入使用隔离替身。"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import tempfile
import time
import zipfile
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw
from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Signal, qVersion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet import appearance, character_frames, config, native_animation, platform_resources
from pet.appearance_flow import AppearanceFlow
from pet.appearance_hub import AppearanceHub
from pet.appearance_import import AppearanceCandidate
from pet.avatar import Avatar
from pet.config import ROOT, Settings, save_settings
from pet.history_controller import PersonalHistory
from pet.live2d_session import SESSION, configure_opengl_sharing
from pet.panel import Panel
from pet.platform_dialog import PlatformDialog

LOG = logging.getLogger(__name__)
VERSION = '11111111-1111-4111-8111-111111111111'


def wait(predicate, message, seconds=15):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate(), message


class Runtime(QObject):
    """真实保存函数写临时 JSON，异步回执保持与生产一致的顺序。"""

    platform_settings_saved = Signal(object, str)
    settings_saved = Signal(object, str)

    def __init__(self, settings, directory):
        super().__init__()
        self.settings, self.directory, self.fail = settings, directory, False

    def persist_platform(self, changes):
        def complete():
            if self.fail:
                self.platform_settings_saved.emit(self.settings, '验收注入：保存失败')
                return
            self.settings = replace(self.settings, **changes)
            save_settings(self.settings, self.directory / 'settings.json')
            self.platform_settings_saved.emit(self.settings, '')
        QTimer.singleShot(20, complete)


class LocalClient:
    """官网协议替身；真实安全安装器仍验证 ZIP/摘要，不访问凭据或 HTTP。"""

    def __init__(self, source):
        self.source, self.requests, self.downloaded = source, [], []

    async def request(self, method, path, *, anonymous=False):
        self.requests.append((method, path, anonymous))
        await asyncio.sleep(1)
        if path == '/resources?limit=100':
            assert anonymous, '公开形象列表不应读取账号凭据'
            return [{'id': VERSION, 'kind': 'IMAGE', 'name': '官网测试形象'}]
        assert path == f'/resources/{VERSION}/versions'
        return [{'id': 'pending', 'validationStatus': 'PENDING'},
                {'id': VERSION, 'validationStatus': 'READY'},
                {'id': 'older', 'validationStatus': 'READY'}]

    async def install(self, resource, version, *, root):
        assert resource == version == VERSION, '必须选择首个 READY 版本'
        self.downloaded.append(version)
        payload = self.source.read_bytes()
        manifest = {
            'schemaVersion': 1, 'resourceId': resource, 'resourceVersionId': version,
            'kind': 'IMAGE', 'name': '官网测试形象', 'version': '1', 'minimumClientVersion': '',
            'capabilities': {}, 'entrypoint': 'image.png', 'dependencies': [],
            'files': [{'path': 'image.png', 'bytes': len(payload),
                       'sha256': hashlib.sha256(payload).hexdigest()}],
        }
        package = self.source.parent / 'online.zip'
        with zipfile.ZipFile(package, 'w') as archive:
            archive.writestr('image.png', payload)
        await asyncio.to_thread(platform_resources.install_package, package, manifest,
                                {'bytes': package.stat().st_size,
                                 'sha256': platform_resources.hash_file(package)}, root)


def inspect(directory, output, report):
    settings = replace(Settings(), observe=False, speak_replies=False,
                       platform_url='http://127.0.0.1:1')
    panel = Panel(settings)
    panel.logs.path = directory / 'logs.txt'
    avatar = Avatar(160)
    runtime = Runtime(settings, directory)
    owner = SimpleNamespace(settings=settings, panel=panel, avatar=avatar, runtime=runtime)
    platform = PlatformDialog(owner, embedded=True)
    platform.client = LocalClient(directory / 'online.png')
    # api() 每次会重建 Client；在实例边界截断，禁止进入真实账号/网络实现。
    platform.api = lambda: platform.client
    hub = AppearanceHub(panel)
    flow = AppearanceFlow(owner, hub, platform, on_applied=lambda: None)
    history = PersonalHistory(owner, flow, platform)
    panel.mount_section('appearance', hub, on_open=flow.present)
    panel.mount_section('resources', platform)

    def check(name, condition):
        report['checks'][name] = bool(condition)
        assert condition, name
        LOG.info('验收通过：%s', name)

    def capture(name):
        assert panel.grab().save(str(output / (name + '.png')))
        if hub.preview.renderer.isVisible():
            assert hub.preview.renderer.grabFramebuffer().save(str(output / (name + '-gl.png')))

    def import_file(path):
        previous = hub.candidate
        hub.import_requested.emit(str(path))
        wait(lambda: not flow.sources.busy, '本地导入没有退场')
        wait(lambda: hub.ready and hub.candidate != previous, '真实预览未就绪：' + hub.status.text())

    def use():
        assert hub.apply_button.isEnabled()
        hub.apply_button.click()
        wait(lambda: not flow.applying.busy, '保存事务没有完成')

    def layout(name, size):
        panel.resize(*size)
        QTest.qWait(150)
        section = panel.sections['appearance']
        button = hub.apply_button
        visible = QRect(button.mapTo(section.viewport(), QPoint()), button.size())
        report.setdefault('layout', {})[name] = {
            'viewport': section.viewport().rect().getRect(), 'apply': visible.getRect(),
            'horizontal_max': section.horizontalScrollBar().maximum(),
            'vertical_max': section.verticalScrollBar().maximum(),
            'busy': hub.busy, 'page': hub.stack.currentIndex(),
        }
        capture(name)
        # 布局失败仍记录为失败，继续采集后续事务证据，最终汇总严格返回非零。
        report['checks'][name] = (section.viewport().rect().contains(visible)
                                  and section.horizontalScrollBar().maximum() == 0)
        LOG.info('布局验收：%s passed=%s', name, report['checks'][name])

    try:
        avatar.show()
        panel.open_section('appearance')
        flow.present()
        wait(lambda: avatar._live2d_active and hub.ready, '默认 Live2D 未真正加载')
        check('default_real_gl', hub.preview.renderer._live2d_active)
        layout('default-720x560', (720, 560))
        layout('default-520x480', (520, 480))
        old_model = avatar._live2d_model
        import_file(directory / 'static.png')
        check('import_only_previews', avatar._live2d_model is old_model and not avatar.image_id)
        use()
        check('image_saved_and_applied', avatar.image_id == owner.settings.avatar_image
              and bool(avatar.image_id) and json.loads((directory / 'settings.json').read_text('utf-8'))
              ['avatar_image'] == avatar.image_id)
        check('opaque_png_supported', not hub.preview.image_failed and bool(avatar.image_id))
        import_file(directory / 'animated.png')
        check('animation_detected', hub.candidate.kind == 'ANIMATION' and hub.preview.native)
        use()
        check('animation_applied', avatar.native_animation and avatar.image_id.endswith('.apng'))
        hub.online_button.click()
        check('busy_disables_repeat', hub.busy and not hub.online_button.isEnabled())
        layout('busy-720x560', (720, 560))
        layout('busy-520x480', (520, 480))
        wait(lambda: not flow.sources.busy, '官网列表没有退场')
        check('anonymous_list', hub.choices.count() == 1 and not platform.client.downloaded)
        hub.choices.setCurrentRow(0)
        layout('choices-720x560', (720, 560))
        layout('choices-520x480', (520, 480))
        hub.choice_button.click()
        wait(lambda: not flow.sources.busy and hub.ready, '官网下载预览失败')
        check('latest_ready_preview', platform.client.downloaded == [VERSION]
              and hub.candidate.name == '官网测试形象' and avatar.native_animation)
        original = avatar.image_id
        runtime.fail = True
        use()
        check('save_failure_preserves_avatar', avatar.image_id == original
              and '保存失败' in hub.status.text())
        runtime.fail = False
        use()
        check('online_applied', avatar.image_id == hub.candidate.image_id and not hub.dirty)
        original = avatar.image_id
        import_file(directory / 'static.png')
        (directory / 'appearances' / hub.candidate.image_id).unlink()
        use()
        check('deleted_candidate_rolls_back', avatar.image_id == owner.settings.avatar_image == original
              and runtime.settings.avatar_image == original and '未更换' in hub.status.text())
        import_file(ROOT / 'assets/xuansi/rigging/xuansi.model3.json')
        candidate = hub.candidate
        check('local_model_real_preview', candidate.kind == 'MODEL'
              and hub.preview.renderer._platform_model_version == candidate.version_id
              and hub.preview.renderer._live2d_active and avatar.image_id != '')
        panel.open_section('chat')
        panel.open_section('appearance')
        wait(lambda: hub.preview.renderer._live2d_active, '切页后未使用的模型草稿未恢复')
        check('draft_survives_navigation', hub.candidate == candidate and hub.dirty and avatar.image_id != '')
        use()
        check('local_model_applied', avatar._live2d_active
              and avatar._platform_model_version == candidate.version_id
              and owner.settings.platform_model_version == candidate.version_id)
        live_model = avatar._live2d_model
        panel.open_section('chat')
        check('preview_releases_only_itself', not hub.preview.renderer._live2d_active
              and avatar._live2d_model is live_model and avatar in SESSION.owners)
        panel.open_section('appearance')
        wait(lambda: hub.preview.renderer._live2d_active, '返回后候选模型未重载')
        panel.hide()
        panel.show()
        wait(lambda: hub.preview.renderer._live2d_active, '重开后候选模型未重载')
        check('reopen_preserves_candidate', hub.candidate == candidate
              and avatar._live2d_model is live_model)
        layout('model-720x560', (720, 560))
        layout('model-520x480', (520, 480))
        # 无效自定义图片必须明确失败，不能把默认图片回退冒充候选成功。
        hub.show_candidate(AppearanceCandidate('IMAGE', '缺失副本', 'f' * 64 + '.png'))
        QTest.qWait(100)
        check('invalid_preview_rejected', not hub.ready and not hub.apply_button.isEnabled()
              and avatar._live2d_model is live_model)
        hub.default_button.click()
        wait(lambda: hub.ready, '默认预览未恢复真实 GL')
        use()
        check('restore_default_real_gl', avatar._live2d_active and not avatar.image_id
              and not avatar._platform_model_version and not owner.settings.platform_model_version)
        # 装配生产历史控制器，成功回执异步落盘；预览、保存失败和回滚均不得计入。
        wait(lambda: len(history.appearances.read()['entries']) == 5, '成功形象历史未完整落盘')
        check('history_records_only_five_successes', len(history.appearances.read()['entries']) == 5
              and not history.appearances.read()['sync']['enabled'])
        hub.history_button.click()
        wait(lambda: history.appearance_dialog.records.count() == 5, '形象历史列表未读取临时文件')
        assert history.appearance_dialog.grab().save(str(output / 'appearance-history.png'))
        check('history_dialog_real_window', history.appearance_dialog.isVisible())
        history.appearance_dialog.records.setCurrentRow(1)  # 刚才成功使用的本机 Live2D。
        history.appearance_dialog.select_button.click()
        wait(lambda: hub.ready and hub.candidate.kind == 'MODEL', '历史形象未恢复到真实预览')
        check('history_restore_only_previews', avatar._platform_model_version == ''
              and owner.settings.platform_model_version == '')
        snapshot = replace(owner.settings, model_path='history-draft.gguf')
        runtime.settings_saved.emit(snapshot, '')
        wait(lambda: len(history.models.read()['entries']) == 1, '模型配置历史未异步保存')
        panel.model_page.history_requested.emit()
        wait(lambda: history.model_dialog.records.count() == 1, '模型配置历史未显示')
        assert history.model_dialog.grab().save(str(output / 'model-history.png'))
        history.model_dialog.select_button.click()
        wait(lambda: panel.model_page.model.text() == 'history-draft.gguf', '模型历史未填写草稿')
        check('model_history_restore_only_draft', owner.settings.model_path != 'history-draft.gguf'
              and runtime.settings.model_path != 'history-draft.gguf')
        check('all_data_is_temporary', flow.sources.image_directory == directory / 'appearances'
              and flow.sources.resource_root == directory / 'resources'
              and history.appearances.path.parent == directory and history.models.path.parent == directory)
        assert all(report['checks'].values()), '存在失败验收项，请检查 report.json'
    finally:
        history.close()
        history.io.pool.waitForDone(4000)
        flow.close()
        platform.shutdown()
        wait(lambda: platform.worker is None, '退出时后台任务未结束')
        panel.hide()
        hub.preview.stop()
        avatar._release_live2d()
        avatar.hide()
        panel.deleteLater()
        avatar.deleteLater()
        QTest.qWait(50)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/verification/appearance-flow')
    output = parser.parse_args().output.absolute()
    output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
    configure_opengl_sharing()
    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setQuitOnLastWindowClosed(False)
    report = {'checks': {}, 'qt': qVersion(), 'pyside': pyside_version,
              'scale_factor': os.environ.get('QT_SCALE_FACTOR', '1'),
              'real': ['Qt 控件', 'OpenGL/Cubism', '导入/安全安装', '后台线程',
                                    '预览/桌宠切换', '临时 JSON 保存'],
              'substitutes': ['官网 Client（禁止 HTTP/凭据）', 'Runtime（仅临时配置）']}
    try:
        with tempfile.TemporaryDirectory(prefix='xuansi-native-appearance-') as temporary, ExitStack() as patches:
            directory = Path(temporary)
            patches.enter_context(patch.object(config, 'DATA', directory))
            image_path = appearance.image_path
            def isolated_image_path(identifier='', explicit_directory=None):
                return image_path(identifier, explicit_directory or directory / 'appearances')
            for module in (appearance, character_frames, native_animation):
                patches.enter_context(patch.object(module, 'image_path', isolated_image_path))
            patches.enter_context(patch.object(appearance, 'DIRECTORY', directory / 'appearances'))
            patches.enter_context(patch.object(platform_resources, 'RESOURCE_ROOT', directory / 'resources'))
            patches.enter_context(patch('httpx.AsyncClient.request', side_effect=AssertionError('禁止真实 HTTP')))
            Image.new('RGBA', (96, 128), '#d86a43').save(directory / 'static.png')
            Image.new('RGBA', (96, 128), '#438e79').save(directory / 'online.png')
            frames = []
            for color in ('#438e79', '#dda64a'):
                image = Image.new('RGBA', (96, 128))
                ImageDraw.Draw(image).ellipse((8, 8, 88, 120), fill=color)
                frames.append(image)
            frames[0].save(directory / 'animated.png', save_all=True, append_images=frames[1:], duration=100, loop=0)
            inspect(directory, output, report)
        report['passed'] = True
    except Exception as exc:
        report['passed'], report['error'] = False, str(exc) or type(exc).__name__
        LOG.exception('原生形象流程验收失败')
    finally:
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        SESSION.shutdown()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
