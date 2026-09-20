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
