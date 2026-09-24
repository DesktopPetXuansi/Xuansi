"""模型决定开关；用假音频验证真实运行时、麦克风代次及同轮恢复。"""

import asyncio
import threading
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import Qt

from pet.config import Settings
from pet.live_input import VoiceUpdate
from pet.memory import MemoryStore
from pet.runtime import Runtime


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr("pet.runtime.sd.stop", lambda: None)
    monkeypatch.setattr("pet.runtime.sd.play", lambda *_: None)
    monkeypatch.setattr("pet.runtime.sd.wait", lambda: None)
    result = Runtime()
    result.audio_activity.set_enabled(False)
    result.memory = MemoryStore(tmp_path / "memory.json")
    yield result
    result.cancel(release=True).result(5)
    result.loop.call_soon_threadsafe(result.loop.stop)
    result.thread.join(2)


def test_model_can_mute_keep_silent_and_resume_in_same_turn(runtime):
    clips, replies = [], []
    decisions = iter([False, None, True])
    runtime.listening = True  # 仅模拟状态，不打开真实设备。
    runtime.reply.connect(lambda _, text, kind: replies.append(text), Qt.ConnectionType.DirectConnection)

    async def chat(*_, on_chunk, on_speech, speech_enabled):
        decision = next(decisions)
        if decision is not None:
            on_speech(decision)
        await on_chunk("完整的确认回复。")
        return "完整的确认回复。"

    def synthesize(text, *_):
        clips.append(text)
        return np.zeros(80), 8000

    runtime.engine.chat = chat
    runtime.audio.synthesize = synthesize
    for index, should_speak in enumerate([False, False, True]):
        # 刻意使用无关键词输入：执行的是模型动作，不能根据输入词语猜测。
        runtime.schedule(runtime._conversation(0, Settings(), f"测试{index}", "chat", None, None)).result(3)
        assert runtime.should_speak(Settings()) is should_speak
        assert runtime.listening and runtime.microphone_epoch == 0
        assert not runtime.microphone.muted.is_set()
        assert len(clips) == (1 if should_speak else 0)
    assert len(replies) == 3 and len(runtime.history) == 6


@pytest.mark.parametrize("kind", ["observation", "preview"])
def test_mute_blocks_observation_and_preview_without_opening_microphone(runtime, kind):
    clips, calls = [], []

    async def chat(*_, **kwargs):
        calls.append(kwargs)
        return "观察回应。"

    runtime.engine.chat = chat
    runtime.audio.synthesize = lambda *_: clips.append(True)
    runtime.set_speech_enabled(False)
    settings = replace(Settings(), speak_observations=True)
    runtime.schedule(runtime._conversation(0, settings, "测试", kind, None, None)).result(3)
    assert not clips and not runtime.listening
    assert not calls or "on_speech" not in calls[0]


def test_late_model_decision_cannot_change_new_request_state(runtime):
    entered, release = threading.Event(), threading.Event()

    async def chat(*_, on_chunk, on_speech, **kwargs):
        entered.set()
        await asyncio.to_thread(release.wait, 2)
        on_speech(False)
        await on_chunk("迟到的回复。")
        return "迟到的回复。"

    runtime.engine.chat = chat
    future = runtime.schedule(runtime._conversation(0, Settings(), "旧请求", "chat", None, None))
    assert entered.wait(1)
    runtime.epoch += 1
    release.set()
    future.result(3)
    assert runtime.speech_override is None and not runtime.history


def test_final_voice_can_resume_when_saved_reply_preference_is_off(runtime):
    clips = []
    runtime.listening = True
    runtime.set_speech_enabled(False)

    async def chat(*_, on_chunk, on_speech, speech_enabled):
        assert not speech_enabled
        on_speech(True)
        await on_chunk("现在可以听到我了。")
        return "现在可以听到我了。"

    def synthesize(text, *_):
        clips.append(text)
        return np.zeros(80), 8000

    runtime.engine.chat = chat
    runtime.audio.synthesize = synthesize
    settings = replace(Settings(), speak_replies=False)
    runtime.accept_voice(0, VoiceUpdate(1, "恢复", final=True), settings).result(2)

    async def finish():
        await runtime.job

    runtime.schedule(finish()).result(3)
    assert clips == ["现在可以听到我了。"]
    assert runtime.listening and not runtime.microphone.muted.is_set()
