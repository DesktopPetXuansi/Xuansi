"""控制中心的可用空间回归；仅运行离屏 Qt，日志写入临时目录。"""

import logging
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QPoint, QRect, Signal
from PySide6.QtWidgets import QApplication, QPushButton

from pet.config import Settings
from pet.panel import Panel
from pet.platform_dialog import PlatformDialog

LOG = logging.getLogger(__name__)


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    window = Panel(Settings())
    window.logs.path = tmp_path / "panel-layout.log"
    window.show()
    application.processEvents()
    yield window
    window.hide()
    window.logs.hide()
    window.deleteLater()
    application.processEvents()


def settle_size(panel, width, height):
    # 布局请求会再次排队，处理两轮事件，不用时间等待掩盖布局问题。
    panel.resize(width, height)
    application = QApplication.instance()
    application.processEvents()
    application.processEvents()
    LOG.info("布局验证：窗口=%sx%s，记录高度=%s", panel.width(), panel.height(), panel.chat.height())


def assert_fully_inside(widget, container):
    bounds = QRect(widget.mapTo(container, QPoint()), widget.size())
    assert widget.isVisible() and container.rect().contains(bounds), (
        f"{widget.metaObject().className()} 未完整可见：控件 {bounds}，容器 {container.rect()}"
    )


def test_ready_window_reserves_space_for_conversation(panel):
    settle_size(panel, 880, 760)
    assert panel.navigation.stack.height() >= 560, "就绪状态页面区域应至少有 560 个逻辑像素"
    assert panel.chat.height() >= 320, "默认窗口应能直接阅读至少 320 个逻辑像素的记录"


def test_conversation_history_grows_with_window(panel):
    settle_size(panel, 880, 760)
    initial_height = panel.chat.height()
    settle_size(panel, 1040, 800)
    assert panel.chat.height() > initial_height, "增高窗口应增加可阅读的对话记录空间"


@pytest.mark.parametrize("size", [(520, 480), (560, 660)])
def test_narrow_conversation_keeps_composer_visible_without_outer_scroll(panel, size):
    settle_size(panel, *size)
    section = panel.sections["chat"]
    send = next(button for button in panel.findChildren(QPushButton) if button.text() == "发送")
    assert panel.size().width() == size[0] and panel.size().height() == size[1]
    assert_fully_inside(panel.input, section.viewport())
    assert_fully_inside(send, section.viewport())
    assert section.verticalScrollBar().maximum() == 0, "对话页不应滚动整个输入区域"


def test_long_status_and_save_failure_do_not_expand_window_width(panel):
    # 模拟运行期长说明和保存失败，覆盖宽度约束，不依赖文案换行位置。
    panel.audio_status.setText("声音回避说明：" + "其他软件发声时暂停朗读，结束后恢复。" * 15)
    panel.live_transcript.setText("正在识别：" + "这是一段较长的语音转写内容。" * 15)
    panel.form.complete("无法写入配置：" + "目录暂不可用，请保留草稿并稍后重试。" * 15)
    settle_size(panel, 520, 480)
    assert panel.width() == 520, "长说明和失败原因应换行，不能撑宽窗口"


def test_valid_long_name_keeps_status_and_composer_usable_when_voice_paused(panel):
    # 名字上限是 40 字；暂停是生产状态，不能让标题挤掉状态或输入区。
    panel.title.setText("玄司" * 20)
    panel.voice_state(True, paused=True)
    panel.live_transcript.setText("这是一段尚未提交的实时语音转写内容。")
    settle_size(panel, 520, 480)
    assert panel.status.width() >= panel.status.minimumSizeHint().width(), "有效名字不能挤掉运行状态"
    assert panel.input.height() >= panel.input.minimumSizeHint().height(), "输入框应保持正常可输入高度"
    assert_fully_inside(panel.input, panel.sections["chat"].viewport())


def test_clearing_live_transcript_removes_preview_and_accessible_content(panel):
    # 关闭麦克风和休眠走 QLabel.clear，必须与 setText 空串使用同一状态更新。
    panel.live_transcript.setText("尚未提交的语音转写")
    assert panel.live_transcript.isVisible() and panel.live_transcript.toolTip()
    panel.live_transcript.clear()
    assert not panel.live_transcript.text()
    assert not panel.live_transcript.toolTip()
    assert not panel.live_transcript.accessibleDescription()
    assert panel.live_transcript.isHidden()


def test_resource_progress_stays_visible_across_tabs_and_resource_refresh(panel):
    class Runtime(QObject):
        platform_settings_saved = Signal(object, str)

    owner = SimpleNamespace(panel=panel, settings=panel.settings, runtime=Runtime())
    platform = PlatformDialog(owner, embedded=True)
    platform.activity_changed.connect(panel.footer.set_activity)
    panel.mount_section("resources", platform)
    panel.open_section("chat")
    platform.set_busy(True)
    assert not platform.isVisible() and panel.footer.isVisible()
    assert "官网资源" in panel.footer.text()
    platform.task_progress("上传样例进度35%", 35)
    # 原有定时器继续更新本机资源，不能覆盖后台操作的进度。
    resources = "仅本机处理 · 可用内存8.0 GB · 麦克风关闭"
    panel.footer.setText(resources)
    assert "35%" in panel.footer.text() and resources in panel.footer.toolTip()
    platform.set_busy(False)
    assert panel.footer.text() == resources


def test_navigation_preserves_all_nine_pages_in_order(panel):
    expected = ("chat", "persona", "memory", "preferences", "model", "appearance", "resources", "upload", "logs")
    bar = panel.navigation.bar
    assert tuple(bar.tabData(index) for index in range(bar.count())) == expected
    for key in expected:
        panel.open_section(key)
        QApplication.instance().processEvents()
        assert panel.navigation.current_key == key
        assert panel.sections[key].isVisible()


@pytest.mark.parametrize("key", ["persona", "preferences", "model"])
def test_narrow_settings_do_not_require_whole_page_horizontal_scroll(panel, key):
    panel.open_section(key)
    settle_size(panel, 520, 480)
    assert panel.width() == 520
    assert panel.sections[key].horizontalScrollBar().maximum() == 0, "设置页应在窄窗口内换行"
