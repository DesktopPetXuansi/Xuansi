"""开关使用临时设置和假声卡，验证持久化、不中断对话及播放中重新开启。"""

import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from pet.app import DesktopPet
from pet.audio_activity import AudioActivity
from pet.config import Settings, load_settings, save_settings
from pet.streaming_speech import SpeechStream


def test_old_settings_default_on_and_disabled_value_survives_reload(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"name":"测试角色"}', encoding="utf-8")
    assert load_settings(path).audio_avoidance
    settings = replace(load_settings(path), audio_avoidance=False)
    save_settings(settings, path)
    assert load_settings(path) == settings
    with pytest.raises(ValueError):
        replace(settings, audio_avoidance="false").validate()


def test_disabled_bypasses_sound_and_failed_meter_reenable_needs_fresh_sample():
    gate = AudioActivity(clock=lambda: 10.0)
    gate.set_enabled(False)
    gate.update(True)
    assert not gate.blocked
    gate.update(None)
    assert not gate.blocked and "已关闭" in gate.status
    gate.set_enabled(True)
    assert gate.blocked
    gate.clock = lambda: 12.0
    gate.update(False)
    assert not gate.blocked


def test_toggle_only_keeps_microphone_busy_state_and_unrelated_settings():
    old = replace(Settings(), persona="保留人设", temperature=0.3)
    checked = []
    gate = AudioActivity()
    owner = SimpleNamespace(
        settings=old,
        busy=True,
        runtime=SimpleNamespace(listening=True, audio_activity=gate),
        panel=SimpleNamespace(
            settings=old,
            status=SimpleNamespace(setText=lambda _: None),
            audio_avoidance_action=SimpleNamespace(setChecked=checked.append),
        ),
        ui=SimpleNamespace(refresh=lambda: None),
    )  # 不提供取消模型、关闭麦克风或修改形象接口。
    new = replace(old, audio_avoidance=False)
    DesktopPet.apply_settings(owner, new, "")
    assert owner.settings == owner.panel.settings == new
    assert checked == [False] and not gate.blocked
    assert owner.busy and owner.runtime.listening


@pytest.mark.asyncio
async def test_reenable_during_stream_stops_and_disabling_again_does_not_replay(monkeypatch):
    gate = AudioActivity(clock=lambda: 10.0)
    gate.set_enabled(False)
    gate.update(True)
    played = []
    started, stopped = threading.Event(), threading.Event()
    monkeypatch.setattr("pet.speech_output.sd.play", lambda *_: (played.append(True), started.set()))
    monkeypatch.setattr("pet.speech_output.sd.wait", lambda: stopped.wait(2))
    monkeypatch.setattr("pet.speech_output.sd.stop", stopped.set)
    async with SpeechStream(gate, lambda _: (np.zeros(10), 8000), lambda: True, lambda _: None) as stream:
        await stream.feed("其他软件有声音，也允许播放。第二段等待播放。")
        assert await asyncio.to_thread(started.wait, 1)
        gate.set_enabled(True)
        assert await asyncio.to_thread(stopped.wait, 1)
        gate.set_enabled(False)
        await stream.feed("这一轮仍然不补播。")
        await asyncio.wait_for(stream.finish(), 1)
    assert played == [True]
