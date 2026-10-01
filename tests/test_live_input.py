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
    for _ in range(4):
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
    for _ in range(4):
        online.feed(np.zeros(4800, dtype=np.float32))
    assert sum(event.final for event in events) == 1


def test_silence_without_recognized_text_never_submits():
    """无声音且无转写时不凭空创建一轮回复。"""
    online, events = fake_online()
    online._decode = lambda *_: ""
    for _ in range(160):
        online.feed(np.zeros(4800, dtype=np.float32))
    assert events == []
