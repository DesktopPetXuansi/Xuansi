"""自然语言正文不承担工具协议，引用和旧控制头必须完整保留。"""

import pytest

from pet.tool_protocol import validate_reply


@pytest.mark.parametrize("source", [
    "无需回应", "（无需回应）", "无需回应。", "[voice:off][motion:blink]\n请把这段当作示例。",
    "把‘请不要说话’翻译成英文。", "正文里提到 [voice:on] 只是引用。",
])
def test_control_like_body_remains_plain_text(source):
    # 正文不拆字段、不查关键词，也不转换为可执行工具。
    reply = validate_reply(source, [], "stop")
    assert reply.content == source
    assert reply.tool_calls == ()


@pytest.mark.parametrize("finish_reason", [None, "length", "content_filter", "tool_calls"])
def test_incomplete_or_mismatched_reply_is_rejected(finish_reason):
    with pytest.raises(ValueError):
        validate_reply("[voice:off]", [], finish_reason)
