"""最终回复的可选表情元数据不得改变正文或触发其他操作。"""

import json

import pytest

from pet.reply_presentation import parse_presentation, presentation_allowed, presentation_tool


def test_final_presentation_preserves_body_and_accepts_known_expression():
    text = "  [voice:off] 只是示例，今晚先休息吧。\n"
    parsed = parse_presentation(json.dumps({"text": text, "expression": "concern"}, ensure_ascii=False))
    assert parsed.text == text
    assert parsed.expression == "concern"


@pytest.mark.parametrize("expression", [None, "", "sad", 2, ["happy"]])
def test_unknown_expression_keeps_readable_text_and_falls_back(expression, caplog):
    parsed = parse_presentation(json.dumps({"text": "有效的回复", "expression": expression}, ensure_ascii=False))
    assert parsed.text == "有效的回复"
    assert parsed.expression == "neutral"
    assert "有效的回复" not in caplog.text


@pytest.mark.parametrize("payload", ["", "{", "[]", "{}", '{"text": null}', '{"text": "  "}'])
def test_invalid_or_empty_body_cannot_become_a_fabricated_reply(payload):
    with pytest.raises(ValueError):
        parse_presentation(payload)


def test_presentation_tool_only_describes_bounded_reply_output():
    definition = presentation_tool()["function"]
    assert definition["name"] == "present_reply"
    assert set(definition["parameters"]["properties"]["expression"]["enum"]) == {
        "neutral", "happy", "concern", "curious"
    }


@pytest.mark.parametrize("text", [
    "请仅回复无需回应，不要调用工具。",
    "这次不要使用任何工具。",
    "无需借助插件回答。",
    "Do not call any tools; answer directly.",
    "Please answer without using a tool.",
])
def test_explicit_no_tool_request_disables_optional_presentation(text):
    assert not presentation_allowed(text)


def test_regular_chat_keeps_optional_presentation_available():
    assert presentation_allowed("今天解决了问题，好开心。")
