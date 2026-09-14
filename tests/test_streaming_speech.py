"""不播放真实声音，用事件证明首段早播、预合成、整轮回避和取消。"""

import asyncio
import threading

import numpy as np
import pytest

from pet.streaming_speech import SpeechChunks, SpeechStream


class Gate:
    blocked = False


def test_short_first_greeting_is_delivered_before_rest_of_sentence():
    chunks = SpeechChunks()
    assert chunks.feed("你好，") == ["你好，"]
    assert chunks.feed("我是玄司，") == []
    assert chunks.feed("很高兴见到你。") == ["我是玄司，很高兴见到你。"]


def test_chunks_preserve_long_text_and_do_not_split_decimal_numbers():
    source = "版本是 3.14，可以继续使用。" + "很长的回答" * 70 + "最后一句。"
    chunker = SpeechChunks()
    parts = []
    for character in source:
        parts.extend(chunker.feed(character))
    parts.extend(chunker.finish())
    assert "".join(parts) == source
    assert max(map(len, parts)) <= 48
    assert "3.14" in parts[0]


@pytest.mark.asyncio
async def test_first_part_plays_before_finish_and_next_part_synthesizes_during_play(monkeypatch):
    started, release, next_ready = threading.Event(), threading.Event(), threading.Event()
    texts, played = [], []

    def synthesize(text):
        texts.append(text)
        if len(texts) == 2:
            next_ready.set()
        return np.full(8, len(texts), dtype=np.float32), 8000

    def play(samples, _):
        played.append(int(samples[0]))
        started.set()

    monkeypatch.setattr("pet.speech_output.sd.play", play)
    monkeypatch.setattr("pet.speech_output.sd.wait", lambda: release.wait(2))
    monkeypatch.setattr("pet.speech_output.sd.stop", release.set)
    async with SpeechStream(Gate(), synthesize, lambda: True, lambda _: None) as stream:
        await stream.feed("第一段。")
        assert await asyncio.to_thread(started.wait, 1)
        await stream.feed("第二段。")
        assert await asyncio.to_thread(next_ready.wait, 1)
        assert played == [1]  # 首段尚未结束，下一段已合成。
        release.set()
        await stream.finish()
    assert played == [1, 2]
    assert texts == ["第一段。", "第二段。"]


@pytest.mark.asyncio
async def test_external_audio_discards_all_pending_parts_without_replay(monkeypatch):
    gate = Gate()
    started, stopped = threading.Event(), threading.Event()
    played = []
    monkeypatch.setattr("pet.speech_output.sd.play", lambda *_: (played.append(True), started.set()))
    monkeypatch.setattr("pet.speech_output.sd.wait", lambda: stopped.wait(2))
    monkeypatch.setattr("pet.speech_output.sd.stop", stopped.set)
    async with SpeechStream(gate, lambda _: (np.zeros(8), 8000), lambda: True, lambda _: None) as stream:
        await stream.feed("第一段。第二段。第三段。")
        assert await asyncio.to_thread(started.wait, 1)
        gate.blocked = True
        assert await asyncio.to_thread(stopped.wait, 1)
        gate.blocked = False
        await stream.feed("恢复安静后也不能补播。")
        await asyncio.wait_for(stream.finish(), 1)
    assert played == [True]


@pytest.mark.asyncio
async def test_cancellation_waits_for_inflight_synthesis_but_never_plays_late_audio(monkeypatch):
    entered, release, output_stopped = threading.Event(), threading.Event(), threading.Event()
    played = []

    def synthesize(_):
        entered.set()
        assert release.wait(2)
        return np.zeros(8), 8000

    monkeypatch.setattr("pet.speech_output.sd.play", lambda *_: played.append(True))
    monkeypatch.setattr("pet.speech_output.sd.stop", output_stopped.set)

    async def run():
        async with SpeechStream(Gate(), synthesize, lambda: True, lambda _: None) as stream:
            await stream.feed("尚在合成的片段。")
            await stream.finish()

    job = asyncio.create_task(run())
    assert await asyncio.to_thread(entered.wait, 1)
    job.cancel()
    assert await asyncio.to_thread(output_stopped.wait, 1)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await job
    assert not played


@pytest.mark.asyncio
async def test_synthesis_failure_degrades_without_blocking_text_producer(monkeypatch):
    calls = []

    def fail(_):
        calls.append(True)
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr("pet.speech_output.sd.stop", lambda: None)
    async with SpeechStream(Gate(), fail, lambda: True, lambda _: None) as stream:
        await asyncio.wait_for(stream.feed("一句。" * 30), 1)
        await asyncio.wait_for(stream.finish(), 1)
    assert calls == [True]
