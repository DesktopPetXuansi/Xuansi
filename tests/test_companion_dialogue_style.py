"""聊天风格只补充生成提示，保留自定义人设、授权与原始正文。"""

from types import SimpleNamespace

import pytest

from pet.config import Settings
from pet.memory import MemoryStore
from pet.tool_dialogue import _system, run_dialogue
from pet.tool_protocol import AssistantReply, ToolCall


def make_runtime(tmp_path, response):
    requests, replies = [], []

    async def complete(_settings, messages, tools=(), **kwargs):
        requests.append((list(messages), tools, kwargs))
        return response

    async def start(_settings):
        return None

    memory = MemoryStore(tmp_path / "memory.json")
    memory.save("用户喜欢绿茶")
    return SimpleNamespace(
        epoch=0, history=[], motion_actions=(), memory=memory,
        engine=SimpleNamespace(complete=complete, start=start),
        should_speak=lambda *_: False,
        reply=SimpleNamespace(emit=lambda _, text, kind: replies.append((text, kind))),
        state=SimpleNamespace(emit=lambda *_: None), requests=requests, replies=replies,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "chat-screen", "voice", "voice-screen", "voice-final"])
async def test_companion_style_preserves_custom_settings_and_single_reply(tmp_path, kind):
    """文字和语音使用同一生成原则，普通回复不增加分析请求或自动记忆。"""
    settings = Settings(
        persona="你是冷静直接的伙伴，以‘阿墨’自称。",
        system_prompt="排错时先给结论，再给必要步骤；保持用户指定的格式。",
        speak_replies=False,
    )
    answer = "  好，今天先放下。\n[voice:off] 这里只是你提到的示例。\n"
    runtime = make_runtime(tmp_path, AssistantReply(answer))
    source = "这个项目又报错了，我折腾了一晚上，不过今天不想继续了。"

    result = await run_dialogue(runtime, 0, settings, source, [], kind, None, None)

    assert len(runtime.requests) == 1
    system = runtime.requests[0][0][0]["content"]
    assert settings.persona in system and settings.system_prompt in system
    assert "聊天回应原则" in system
    assert "倾诉" in system and "明确任务" in system and "不想继续" in system
    # 本机真实对照暴露过臆测通宵和劝人想开的回复，提示必须约束这些失误。
    assert "不要淡化" in system and "不要假设没有睡觉" in system
    assert "保存请求，成功写入之后才确认已记住" in system
    assert "不能声称已替换旧记忆" in system and "选中对应条目" in system
    assert "不要提工具名称" in system and "不要声称能替用户操作" in system
    assert "save_memory、set_speech_enabled、play_motion则只执行用户本轮明确要求" in system
    assert result.content == answer
    assert runtime.replies == [(answer, kind)]
    assert runtime.history[-1]["content"] == answer
    assert runtime.history[0]["content"] == [{"type": "text", "text": source}]
    assert runtime.memory.read() == "用户喜欢绿茶"


@pytest.mark.asyncio
async def test_observation_does_not_inherit_companion_chat_instructions(tmp_path):
    """后台观察仍可独立安静结束，不产生虚构聊天或修改会话。"""
    response = AssistantReply("", (ToolCall("quiet", "finish_observation", "{}"),), "tool_calls")
    runtime = make_runtime(tmp_path, response)

    result = await run_dialogue(runtime, 0, Settings(), "后台观察", [], "observation", None, None)

    system = runtime.requests[0][0][0]["content"]
    assert "聊天回应原则" not in system
    assert "没有用户聊天请求" in system
    assert "不寒暄、不问要不要聊天" in system
    assert result.content is None and not runtime.replies and not runtime.history
    assert runtime.memory.read() == "用户喜欢绿茶"


def test_proactive_event_does_not_inherit_human_chat_style(tmp_path):
    """主动事件另有事件来源，不能套用真人正在倾诉的提示。"""
    runtime = make_runtime(tmp_path, AssistantReply(""))
    context = SimpleNamespace(kind="proactive", runtime=runtime, selected_tts="fast")

    system = _system(Settings(), context, False)

    assert "聊天回应原则" not in system["content"]
