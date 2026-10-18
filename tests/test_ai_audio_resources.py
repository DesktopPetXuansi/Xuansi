"""语音资源目录和组件选择独立于本地/在线大模型，拥塞必须可见。"""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from pet.ai.settings import AISettings
from pet.audio_models import AudioModels
from pet.config import Settings
from pet.microphone import Microphone
from pet.model_tools import ToolContext
from pet.preferences import PreferencesPage
from pet.runtime import Runtime


@pytest.fixture(scope='module')
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.mark.parametrize('components,previous,expected', [
    (('realtime',), False, True), (('realtime',), True, True),
    (('asr',), True, False), (('asr',), False, False),
    (('asr', 'realtime'), False, False), (('asr', 'realtime'), True, True),
    ((), False, False), ((), True, True),
])
def test_voice_mode_matches_installed_components_in_preferences(qapp, components, previous, expected):
    """单识别组件固定模式，设备入口与真正可用的识别能力对齐。"""
    settings = replace(Settings(), realtime_voice=previous, ai=AISettings(voice_components=components))
    page = PreferencesPage(settings)
    try:
        assert page.realtime.isChecked() is expected
        assert page.realtime.isEnabled() is ('asr' in components and 'realtime' in components)
        assert page.device.isEnabled() is bool(set(components) & {'asr', 'realtime'})
        page.set_devices([(7, '合成麦克风')], 7)
        saved = page.apply(settings)
        assert saved.realtime_voice is expected and saved.input_device == 7
    finally:
        page.close()


def test_audio_directory_change_releases_previous_sessions(tmp_path):
    audio = AudioModels()
    audio.recognizer = audio.tts = object()
    audio.configure_root(tmp_path)
    assert audio.root == tmp_path
    assert audio.recognizer is None and audio.tts is None


def test_uninstalled_tts_cannot_be_enabled_by_runtime_override():
    settings = replace(Settings(), ai=AISettings(voice_components=()))
    runtime = SimpleNamespace(speech_override=True)
    assert not Runtime.should_speak(runtime, settings)


def test_uninstalled_voice_controls_are_not_advertised_as_executable_tools():
    settings = replace(Settings(), ai=AISettings(voice_components=()))
    runtime = SimpleNamespace(epoch=0, motion_actions=(), should_speak=lambda *_: False)
    tools = ToolContext(runtime, 0, settings, 'chat', '你好', None, None).tools()
    names = {tool['function']['name'] for tool in tools}
    assert 'save_memory' in names
    assert not names.intersection(('set_speech_enabled', 'select_tts_engine'))


def test_microphone_reports_overflow_and_discards_incomplete_utterance(monkeypatch):
    states = []
    mic = Microphone(lambda _: None, lambda text: (states.append(text), mic.stop() if '拥塞' in text else None))

    class Input:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            for _ in range(25):
                mic._callback(np.zeros((1600, 1), dtype=np.float32), 1600, None, None)

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr('pet.microphone.sd.InputStream', Input)
    # 没有拥塞保护的旧代码无法退出，用Empty的受控读替代无限等待。
    reads = 0
    original_get = mic.frames.get

    def bounded_get(*args, **kwargs):
        nonlocal reads
        reads += 1
        if reads > 25:
            mic.stop()
        return original_get(*args, **kwargs)

    monkeypatch.setattr(mic.frames, 'get', bounded_get)
    mic._run(-1)
    assert any('拥塞' in state for state in states)
