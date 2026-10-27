"""真实 Qt 音色切换回归；只操作内存表单，不播放或写入用户配置。"""

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from pet.config import Settings
from pet.preferences import PreferencesPage


@pytest.fixture
def preferences(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    pages = []

    def create(settings):
        page = PreferencesPage(settings)
        pages.append(page)
        return page

    yield create
    for page in pages:
        page.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('speaker', [0, 17, 102])
def test_natural_voice_survives_switch_to_fast_and_back(preferences, speaker):
    settings = replace(Settings(), tts_engine='natural', speaker=speaker)
    page = preferences(settings)

    page.tts_engine.setCurrentIndex(page.tts_engine.findData('fast'))
    fast = page.apply(settings).validate()
    assert fast.tts_engine == 'fast' and fast.speaker == 0
    assert not page.speaker.isEnabled()

    page.tts_engine.setCurrentIndex(page.tts_engine.findData('natural'))
    restored = page.apply(settings).validate()
    assert restored.tts_engine == 'natural' and restored.speaker == speaker
    assert page.speaker.isEnabled()
    assert settings.speaker == speaker


def test_first_natural_default_does_not_overwrite_later_voice_edits(preferences):
    settings = Settings()
    page = preferences(settings)
    page.tts_engine.setCurrentIndex(page.tts_engine.findData('natural'))
    assert page.speaker.value() == 46

    for speaker in (73, 0, 102):
        page.speaker.setValue(speaker)
        page.tts_engine.setCurrentIndex(page.tts_engine.findData('fast'))
        assert page.apply(settings).validate().speaker == 0
        page.tts_engine.setCurrentIndex(page.tts_engine.findData('natural'))
        assert page.apply(settings).validate().speaker == speaker
