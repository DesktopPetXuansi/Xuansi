"""空识别只更新状态；用事件替身验证不弹气泡、不创建对话且继续监听。"""

from types import SimpleNamespace

import pytest

from pet.app import DesktopPet
from pet.live_input import VoiceUpdate


@pytest.fixture
def feedback():
    bubbles, messages, accepted = [], [], []
    labels = {"panel": "", "quick": ""}
    transcript = SimpleNamespace(setText=lambda _: None)
    owner = SimpleNamespace(
        paused=False, fullscreen=False, busy=False, voice_enabled=True,
        last_voice_notice=float("-inf"), last_external=(0, 0), settings=object(),
        runtime=SimpleNamespace(epoch=3, microphone_epoch=7, listening=True,
                                accept_voice=lambda *args: accepted.append(args)),
        avatar=SimpleNamespace(bubble=SimpleNamespace(present=lambda *args: bubbles.append(args))),
        panel=SimpleNamespace(
            live_transcript=transcript, append=lambda *args: messages.append(args),
            status=SimpleNamespace(setText=lambda text: labels.update(panel=text)),
            with_screen=SimpleNamespace(isChecked=lambda: False),
        ),
        ui=SimpleNamespace(quick=SimpleNamespace(
            live_transcript=transcript,
            status=SimpleNamespace(setText=lambda text: labels.update(quick=text)),
        )),
    )
    owner.on_state = lambda *args: DesktopPet.on_state(owner, *args)
    owner.on_failed = lambda *args: DesktopPet.on_failed(owner, *args)
    owner._begin = lambda: setattr(owner, "busy", True)
    return owner, bubbles, messages, accepted, labels


def test_repeated_empty_recognition_stays_quiet_and_listening(feedback):
    owner, bubbles, messages, accepted, labels = feedback
    for turn in range(3):
        DesktopPet.on_voice_update(owner, 7, VoiceUpdate(turn, "", final=True))

    assert not bubbles and not messages and not accepted
    assert owner.runtime.listening and owner.voice_enabled and not owner.busy
    assert labels["panel"] == labels["quick"] and "继续聆听" in labels["panel"]

    # 空话段之后仍接受正常一句，不用用户重新开麦。
    DesktopPet.on_voice_update(owner, 7, VoiceUpdate(3, "你好", final=True))
    assert len(accepted) == 1 and accepted[0][1].text == "你好"
    assert messages == [("你", "你好")] and owner.busy


def test_actual_failure_keeps_visible_feedback(feedback):
    owner, bubbles, messages, _, _ = feedback
    DesktopPet.on_failed(owner, 3, "麦克风无法开启，请检查输入设备")
    assert len(bubbles) == 1
    assert messages == [("系统提示", "麦克风无法开启，请检查输入设备")]


def test_stale_empty_recognition_cannot_overwrite_current_state(feedback):
    owner, bubbles, messages, accepted, labels = feedback
    DesktopPet.on_voice_update(owner, 6, VoiceUpdate(0, "", final=True))
    assert labels == {"panel": "", "quick": ""}
    assert not bubbles and not messages and not accepted
