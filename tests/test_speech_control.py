"""模型控制头只执行一次；跨包、不完整和正文中的字样不能泄漏或误执行。"""

import pytest

from pet.speech_control import SpeechDirective


@pytest.mark.parametrize("action, expected", [("off", [False]), ("on", [True]), ("keep", [])])
def test_directive_is_consumed_before_body_at_every_split(action, expected):
    source = f"[voice:{action}]\n这是回复正文。"
    for split in range(len(source) + 1):
        changes = []
        directive = SpeechDirective(changes.append)
        parts = [directive.feed(source[:split]), directive.feed(source[split:])]
        directive.finish()
        assert changes == expected
        assert "".join(parts) == directive.text == "这是回复正文。"


def test_body_that_quotes_directive_never_changes_state_again():
    changes = []
    directive = SpeechDirective(changes.append)
    assert directive.feed("[voice:keep]\n代码示例：[voice:off]\n") == "代码示例：[voice:off]\n"
    directive.finish()
    assert not changes


@pytest.mark.parametrize("source", ["", "[voice:o", "[voice:off]", "[voice:off]\n"])
def test_incomplete_response_is_reported(source):
    directive = SpeechDirective(lambda _: None)
    directive.feed(source)
    with pytest.raises(RuntimeError, match="语音控制"):
        directive.finish()


@pytest.mark.parametrize("source", ["普通回复", "[voice:toggle]\n秘密正文", "[voice:OFF]\n", "x" * 100])
def test_invalid_header_never_executes_or_exposes_private_content(source):
    changes = []
    directive = SpeechDirective(changes.append)
    with pytest.raises(RuntimeError, match="语音控制") as error:
        directive.feed(source)
    assert not changes and not directive.text
    assert "秘密正文" not in str(error.value)
