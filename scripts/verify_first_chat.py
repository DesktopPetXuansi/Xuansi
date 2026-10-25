"""首次聊天原生验收：独立临时配置与记忆、真实本地模型；不启麦、截屏或调用在线 API。"""

import argparse
import json
import logging
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QObject, QPoint, QRect, Slot
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet import inference
from pet.ai.settings import AISettings
from pet.config import Settings
from pet.conversation_issues import ConversationIssue
from pet.first_chat import FirstChatFlow
from pet.first_chat_state import read_completed
from pet.memory import MemoryStore
from pet.panel import Panel
from pet.runtime import Runtime

LOG = logging.getLogger(__name__)


def wait_until(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('原生首次聊天验收等待超时，请检查隔离日志。')
        QTest.qWait(20)


class VerificationSession(QObject):
    def __init__(self, settings, temporary):
        super().__init__()
        self.settings = settings
        self.paused = self.busy = False
        self.shutdown_complete = False
        self.delivered = []
        self.failures = []
        self.panel = Panel(settings)
        self.panel.logs.path = temporary / 'unused-log-viewer.log'
        self.runtime = Runtime()
        self.runtime.current_settings = settings
        self.runtime.memory = MemoryStore(temporary / 'memory.json')
        self.panel.speech_button.setChecked(self.runtime.should_speak(settings))
        self.panel.speech_button.setText('朗读关闭')
        self.panel.audio_status.setText('文字聊天不需要麦克风或朗读。')
        self.flow = FirstChatFlow(self, path=temporary / 'first-chat.json')
        self.panel.send_requested.connect(self.send)
        self.runtime.reply.connect(self.reply)
        self.runtime.failed.connect(self.failed)
        self.runtime.state.connect(self.state)
        self.runtime.finished.connect(self.finished)
        self.runtime.shutdown_done.connect(self.stopped)

    @Slot(str, bool)
    def send(self, text, with_screen):
        assert not with_screen
        self.busy = True
        self.panel.append('你', text)
        self.runtime.ask(self.settings, text, kind='chat', position=None)

    @Slot(int, str, str)
    def reply(self, epoch, text, kind):
        if epoch == self.runtime.epoch:
            self.delivered.append(text)
            self.panel.append('玄司', text)

    @Slot(int, str)
    def failed(self, epoch, message):
        if epoch == self.runtime.epoch:
            self.failures.append(message)
            self.panel.append('系统提示', message)

    @Slot(int, str)
    def state(self, epoch, text):
        if epoch == self.runtime.epoch:
            self.panel.status.setText(text)

    @Slot(int)
    def finished(self, epoch):
        if epoch == self.runtime.epoch:
            self.busy = False

    @Slot()
    def stopped(self):
        self.shutdown_complete = True

    def close(self):
        self.flow.close()
        self.runtime.shutdown()
        wait_until(lambda: self.shutdown_complete)
        self.runtime.loop.call_soon_threadsafe(self.runtime.loop.stop)
        self.runtime.thread.join(5)
        assert not self.runtime.thread.is_alive()
        self.panel.hide()


def capture(panel, output, name, size):
    panel.resize(*size)
    panel.open_section('chat')
    QTest.qWait(60)
    viewport = panel.sections['chat'].viewport()
    send = next(button for button in panel.findChildren(QPushButton) if button.text() == '发送')
    assert all(viewport.rect().contains(QRect(widget.mapTo(viewport, QPoint()), widget.size()))
               for widget in (panel.input, send))
    assert panel.chat.height() >= 64 and panel.sections['chat'].verticalScrollBar().maximum() == 0
    assert panel.sections['chat'].horizontalScrollBar().maximum() == 0
    assert [panel.width(), panel.height()] == list(size)
    if panel.first_chat.toggle.isChecked():
        assert viewport.rect().contains(QRect(panel.first_chat.mapTo(viewport, QPoint()), panel.first_chat.size()))
        for button in (panel.first_chat.action, panel.first_chat.example):
            assert panel.first_chat.rect().contains(QRect(button.mapTo(panel.first_chat, QPoint()), button.size()))
            assert viewport.rect().contains(QRect(button.mapTo(viewport, QPoint()), button.size()))
    path = output / f'{name}.png'
    assert panel.grab().save(str(path))
    return {'screenshot': path.name, 'size': list(size), 'dpr': panel.devicePixelRatioF(),
            'composer_visible': True, 'history_height': panel.chat.height()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--projector', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert args.model.is_file() and args.projector.is_file()
    assert (args.runtime_root / 'runtime' / 'llama').is_dir()
    args.output.mkdir(parents=True, exist_ok=True)
    result_path = args.output / 'result.json'
    result_path.write_text(json.dumps({'passed': False, 'status': 'running'}), encoding='utf-8')
    logging.basicConfig(filename=args.output / 'isolated-runtime.log', level=logging.INFO,
                        encoding='utf-8', format='%(asctime)s %(name)s %(message)s')
    # 仅复用只读计算后端；配置、记忆和首次成功标记全部位于新的临时目录。
    inference.ROOT = args.runtime_root.resolve()
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    settings = replace(Settings(), observe=False, speak_replies=False, realtime_voice=False,
                       model_path=str(args.model.resolve()), projector_path=str(args.projector.resolve()),
                       max_tokens=128, ai=AISettings(policy='local_only', local_model='qwen3.5-4b',
                                                    voice_components=()))
    with tempfile.TemporaryDirectory(prefix='xuansi-first-chat-') as directory:
        temporary = Path(directory)
        session = VerificationSession(settings, temporary)
        try:
            wait_until(lambda: session.flow.loaded)
            assert not session.flow.completed and not session.runtime.listening
            records = [capture(session.panel, args.output, 'first-use-720x560', (720, 560)),
                       capture(session.panel, args.output, 'first-use-520x480', (520, 480))]
            session.panel.first_chat.example.click()
            assert session.panel.input.text() and not session.busy
            assert not (temporary / 'first-chat.json').exists()
            session.panel._send()
            assert session.busy, '必须通过既有发送入口，不能仅手动发成功信号。'
            wait_until(lambda: not session.busy, seconds=180)
            assert not session.failures, '真实本地请求失败，请检查隔离日志和界面。'
            wait_until(lambda: read_completed(temporary / 'first-chat.json'))
            assert session.delivered and session.flow.completed
            records.append(capture(session.panel, args.output, 'completed-720x560', (720, 560)))
            # 只注入受控通知，验证窄窗恢复操作；认证/额度真实分流另由运行时测试覆盖。
            issue = ConversationIssue('恢复场景演示：服务拒绝访问，请检查 API Key 与模型权限后保存。',
                                      'model', '检查模型设置')
            session.runtime.request_issue.emit(session.runtime.epoch, issue)
            records.append(capture(session.panel, args.output, 'recovery-520x480', (520, 480)))
            session.panel.first_chat.action.click()
            assert session.panel.navigation.current_key == 'model'
            assert not session.runtime.listening and not session.panel.with_screen.isChecked()
            result = {'passed': True, 'engine': 'real-local', 'model': args.model.name,
                      'pyside': pyside_version, 'reply_characters': sum(map(len, session.delivered)),
                      'completion_marker': json.loads((temporary / 'first-chat.json').read_text()),
                      'microphone_started': False, 'online_api_used': False, 'screen_captured': False,
                      'recovery_screenshot_uses_injected_notice': True, 'screenshots': records}
        finally:
            session.close()
        # 清理也属于验收，模型与后台线程确实退出后才发布成功结果。
        result['runtime_thread_stopped'] = True
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        LOG.info('原生首次聊天验收通过；文字长度=%s', result['reply_characters'])
        print(json.dumps({'passed': True, 'screenshots': len(records), 'real_local_reply': True}))


if __name__ == '__main__':
    main()
