"""句中结果只预览；长句不能因为达到时长限制而触发回复。"""

import numpy as np

from pet.live_input import OnlineInput, PartialTurn


def fake_online():
    events = []
    online = OnlineInput.__new__(OnlineInput)
    online.emit = events.append
    online.turn = PartialTurn()
    online.stream = object()
    online.silence = online.elapsed = 0.0
    online.voiced = False
    online.quiet = False
    online.last_text = online.prefix = ""
    online._decode = lambda *_: "用户还在继续说话"
    online.recognizer = type("FakeRecognizer", (), {"create_stream": lambda _: object()})()
    return online, events


def test_partial_is_not_final():
    turn = PartialTurn()
    assert not turn.update("请帮我介绍一下").final
    assert not turn.update("请帮我介绍一下你自己").final
    final = turn.update("请帮我介绍一下你的功能", final=True)
    assert final.final and final.text.endswith("你的功能")
    assert turn.update("下一句话").turn == final.turn + 1


def test_short_pause_is_not_end_but_400ms_submits():
    online, events = fake_online()
    online.feed(np.ones(4800, dtype=np.float32) * 0.03)
    for _ in range(3):
        online.feed(np.zeros(4800, dtype=np.float32))
    assert not any(event.final for event in events)
    online.feed(np.zeros(4800, dtype=np.float32))
    assert sum(event.final for event in events) == 1


def test_continuous_speech_does_not_trigger_at_15_seconds():
    online, events = fake_online()
    for _ in range(160):
        online.feed(np.ones(4800, dtype=np.float32) * 0.03)
    assert not any(event.final for event in events)


def test_recognized_quiet_speech_submits_after_pause():
    """真实转写是轻声输入的证据，不能被固定音量门限吞掉。"""
    online, events = fake_online()
    online.feed(np.full(4800, 0.003, dtype=np.float32))
    for _ in range(8):
        online.feed(np.zeros(4800, dtype=np.float32))
    final = [event for event in events if event.final]
    assert len(final) == 1
    assert final[0].text == "用户还在继续说话"


def test_quiet_speech_new_words_keep_turn_open():
    """持续出现新识别文字时，低音量不能造成句中抢答。"""
    online, events = fake_online()
    for index in range(20):
        online._decode = lambda *_, index=index: "轻声说话" + str(index)
        online.feed(np.full(4800, 0.003, dtype=np.float32))
    assert not any(event.final for event in events)
    for _ in range(8):
        online.feed(np.zeros(4800, dtype=np.float32))
    assert sum(event.final for event in events) == 1


def test_quiet_speech_waits_across_recognizer_chunk_gaps():
    """真实在线模型约每 600ms 更新；不能在两次更新之间截断轻声。"""
    online, events = fake_online()
    for index in range(24):
        online._decode = lambda *_, index=index: "轻声连续输入" + str(index // 6)
        online.feed(np.full(4800, 0.003, dtype=np.float32))
    assert not any(event.final for event in events)
    for _ in range(8):
        online.feed(np.zeros(4800, dtype=np.float32))
    assert sum(event.final for event in events) == 1


def test_normal_voice_becoming_quiet_does_not_submit_mid_sentence():
    """开头较响不能让随后轻声绕过分块识别的等待。"""
    online, events = fake_online()
    for index in range(24):
        online._decode = lambda *_, index=index: "由响变轻" + str(index // 6)
        level = 0.03 if index == 0 else 0.003
        online.feed(np.full(4800, level, dtype=np.float32))
    assert not any(event.final for event in events)
    for _ in range(8):
        online.feed(np.zeros(4800, dtype=np.float32))
    assert sum(event.final for event in events) == 1


def test_low_volume_continuation_waits_before_first_recognizer_text():
    """首批转写尚未到达时，响声后的轻声也不能被当作结束静音。"""
    online, events = fake_online()
    # 对齐真实识别器：短输入尚无结果，提前补尾部静音只能得到第一个字。
    online._decode = lambda samples, _: "你" if len(samples) > 4800 else ""
    online.feed(np.full(4800, 0.03, dtype=np.float32))
    for _ in range(5):
        online.feed(np.full(4800, 0.003, dtype=np.float32))
    assert not any(event.final for event in events)

    online._decode = lambda *_: "你好，请用一句话介绍一下自己"
    online.feed(np.full(4800, 0.003, dtype=np.float32))
    for _ in range(8):
        online.feed(np.zeros(4800, dtype=np.float32))
    final = [event for event in events if event.final]
    assert len(final) == 1
    assert final[0].text.endswith("介绍一下自己")


def test_silence_without_recognized_text_never_submits():
    """无声音且无转写时不凭空创建一轮回复。"""
    online, events = fake_online()
    online._decode = lambda *_: ""
    for _ in range(160):
        online.feed(np.zeros(4800, dtype=np.float32))
    assert events == []
