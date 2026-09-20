"""在线收音的暂停与关闭行为；不访问声卡。"""

import numpy as np

from pet.live_input import VoiceUpdate
from pet.microphone import Microphone


def test_only_final_pauses_input_until_reply_finishes():
    events = []
    mic = Microphone(lambda _: None, lambda _: None, on_update=events.append)
    mic._online_update(VoiceUpdate(0, "请听我"))
    assert not mic.muted.is_set()
    mic._online_update(VoiceUpdate(0, "请听我说完", final=True))
    assert mic.muted.is_set()
    mic._callback(np.ones((1600, 1), dtype=np.float32), 1600, None, None)
    assert mic.frames.empty()
    mic.muted.clear()
    mic._callback(np.ones((1600, 1), dtype=np.float32), 1600, None, None)
    assert mic.frames.qsize() == 1
    mic.stop()
    mic._online_update(VoiceUpdate(1, "已经关闭", final=True))
    assert len(events) == 2


def test_closed_while_loading_model_does_not_open_device(monkeypatch):
    mic = Microphone(lambda _: None, lambda _: None, on_update=lambda _: None)
    monkeypatch.setattr("pet.microphone.OnlineInput", lambda _: mic.stop())
    opened = []
    monkeypatch.setattr("pet.microphone.sd.InputStream", lambda **_: opened.append(True))
    mic._run(-1)
    assert not opened
