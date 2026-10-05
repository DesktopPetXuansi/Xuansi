"""隔离控制采样与正文采样；受控 HTTP 不替代真实模型的语义验收。"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

import httpx
import pytest

from pet.config import Settings
from pet.inference import LocalEngine
from pet.speech_control import ControlCallbacks

LOG = logging.getLogger(__name__)
BODY = "我理解你的意思，继续陪你聊。"
CONFIRMATION = "你是想把刚才的事项保存为长期记忆吗？确认后我再保存。"
CONTEXT = [
    {"role": "user", "content": "先不要出声，等我说现在可以了，你再恢复语音。"},
    {"role": "assistant", "content": "好的，我先安静地用文字陪你。"},
]
MEMORY_CONTEXT = [
    {"role": "user", "content": "我喜欢喝绿茶。"},
    {"role": "assistant", "content": "绿茶的清香确实适合午后。"},
]


@dataclass
class SamplingService:
    """模拟已复现的边界：随机采样会误选控制头，确定性采样保留给定意图。"""

    voice: str
    wrong_voice: str
    memory: str | None = None
    memory_intent: str | None = None
    authorization: str = "save"
    body: str = BODY
    control_temperatures: list[float] = field(default_factory=list)
    body_temperatures: list[float] = field(default_factory=list)
    control_messages: list[list[dict]] = field(default_factory=list)
    authorization_messages: list[list[dict]] = field(default_factory=list)
    authorization_temperatures: list[float] = field(default_factory=list)
    body_messages: list[list[dict]] = field(default_factory=list)
    saved_memory: list[str] = field(default_factory=list)
    body_memory_counts: list[int] = field(default_factory=list)

    async def __call__(self, request):
        payload = json.loads(request.content)
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        assert request.url.path == "/v1/chat/completions"
        grammar = payload.get("grammar", "")
        authorization_check = "memory_intent" in grammar and "voice" not in grammar and "motion" not in grammar
        response_format = payload.get("response_format", {})
        json_control = (
            response_format.get("type") in {"json_object", "json_schema"}
            or "json_schema" in payload
            or all(part in grammar for part in ("{", "voice", "memory"))
        )
        # 只读模型输出协议，不检查用户句子中的词，允许头/正文分开或正文固定头。
        voices = set(re.findall(r'"(on|off|keep)"|\[voice:(on|off|keep)\]', grammar))
        controls = not authorization_check and (json_control or len(voices) > 1)
        has_body = not authorization_check and not json_control and (not grammar or r"[^\x00]+" in grammar)
        temperature = payload["temperature"]
        if authorization_check:
            self.authorization_messages.append(payload["messages"])
            self.authorization_temperatures.append(temperature)
            assert not self.saved_memory, "独立授权复核必须先于保存执行"
            assert all(word in payload["messages"][0]["content"] for word in ("记忆", "授权", "复核"))
            content = json.dumps({"memory_intent": self.authorization})
        elif controls:
            self.control_messages.append(payload["messages"])
            self.control_temperatures.append(temperature)
            voice = self.voice if temperature == 0 else self.wrong_voice
            content = (
                json.dumps({
                    "memory_intent": self.memory_intent or ("save" if self.memory is not None else "none"),
                    "voice": voice, "motion": "none", "memory": self.memory,
                }, ensure_ascii=False)
                if json_control else f"[voice:{voice}][motion:none]\n"
            )
        else:
            fixed = re.search(r"\[voice:(on|off|keep)\]", grammar)
            content = f"[voice:{fixed[1]}][motion:none]\n" if fixed else ""
        if has_body:
            self.body_messages.append(payload["messages"])
            self.body_temperatures.append(temperature)
            self.body_memory_counts.append(len(self.saved_memory))
            content += self.body
        LOG.info("模拟模型采样 control=%s authorization=%s body=%s temperature=%s",
                 controls, authorization_check, has_body, temperature)
        if not payload["stream"]:
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        # 故意把控制头跨包，验证决定先于首段正文交付。
        chunks = [content[:5], content[5:16], content[16:]]
        events = [
            "data: " + json.dumps({"choices": [{"delta": {"content": chunk}}]}) + "\n\n"
            for chunk in chunks if chunk
        ]
        return httpx.Response(200, text="".join(events) + "data: [DONE]\n\n")


async def converse(monkeypatch, service, settings, text, enabled, streaming, history, *, remember=False):
    events = []

    async def start(_):
        # 避免创建模型进程；仅保留真实推理层和解析器。
        pass

    async def receive(chunk):
        events.append(("text", chunk))

    async def save_memory(note):
        # 刻意让保存跨一次异步调度，正文请求必须等待实际完成。
        events.append(("memory-start", note))
        await asyncio.sleep(0)
        service.saved_memory.append(note)
        events.append(("memory", note))

    def apply_speech(value):
        events.append(("speech", value))

    callbacks = (
        ControlCallbacks(apply_speech, lambda action: None, (), remember=save_memory)
        if remember else apply_speech
    )
    engine = LocalEngine()
    monkeypatch.setattr(engine, "start", start)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(service), base_url="http://127.0.0.1"
    ) as client:
        engine.client = client
        answer = await engine.chat(
            settings, text, [], history, on_chunk=receive if streaming else None,
            on_speech=callbacks, speech_enabled=enabled,
        )
    return answer, events


def assert_sampling_and_delivery(service, settings, answer, events, expected, streaming):
    assert [value for kind, value in events if kind == "speech"] == expected
    assert service.control_temperatures, "控制意图必须由模型判断，不能改成输入关键词匹配"
    assert set(service.control_temperatures) == {0.0}, "控制采样不能继承用户的正文温度"
    assert service.body_temperatures and set(service.body_temperatures) == {settings.temperature}
    assert answer == BODY and "[voice:" not in answer
    if streaming:
        assert "".join(value for kind, value in events if kind == "text") == BODY
        assert [kind for kind, _ in events[:len(expected)]] == ["speech"] * len(expected)


def assert_confirmation_delivery(service, answer, events, expected, streaming):
    # 模型负责判定意图；待确认问题由程序交付，不能随机生成虚假的保存确认。
    assert answer == CONFIRMATION
    assert service.control_temperatures and set(service.control_temperatures) == {0.0}
    assert service.saved_memory == []
    assert not any(kind == "memory-start" for kind, _ in events)
    assert service.body_messages == [] and service.body_temperatures == []
    assert [value for kind, value in events if kind == "speech"] == expected
    if streaming:
        assert "".join(value for kind, value in events if kind == "text") == CONFIRMATION
        assert [kind for kind, _ in events[:len(expected)]] == ["speech"] * len(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize("temperature", [0.35, 0.7, 1.1])
async def test_ordinary_reply_keeps_speech_while_preserving_body_temperature(
    monkeypatch, streaming, temperature
):
    settings = Settings(temperature=temperature)
    service = SamplingService("keep", "off")
    answer, events = await converse(
        monkeypatch, service, settings, "你好喜出生用一句话介绍一下自己", True, streaming, []
    )
    assert_sampling_and_delivery(service, settings, answer, events, [], streaming)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize(
    "text, enabled, voice, expected, history",
    [
        pytest.param("今天工作有点累", True, "keep", [], [], id="ordinary-enabled"),
        pytest.param("今天工作有点累", False, "keep", [], [], id="ordinary-muted"),
        pytest.param("把‘请不要说话’翻译成英文。", True, "keep", [], [], id="quoted-request"),
        pytest.param("不要关闭语音，我还想听你说。", True, "on", [True], [], id="negated-stop"),
        pytest.param("我正在开会，你用文字陪我就好。", True, "off", [False], [], id="indirect-stop"),
        pytest.param("现在可以了。", False, "on", [True], CONTEXT, id="contextual-resume"),
    ],
)
async def test_control_sampling_preserves_model_semantics_and_recent_context(
    monkeypatch, streaming, text, enabled, voice, expected, history
):
    settings = Settings()
    wrong_voice = {"keep": "off" if enabled else "on", "off": "on", "on": "off"}[voice]
    service = SamplingService(voice, wrong_voice)
    answer, events = await converse(monkeypatch, service, settings, text, enabled, streaming, history)
    assert_sampling_and_delivery(service, settings, answer, events, expected, streaming)
    # 语义由模拟模型预先给定，确认真实推理层收到完整引用、否定或上下文。
    assert any(
        messages[-1]["content"][0]["text"] == text and messages[1:1 + len(history)] == history
        for messages in service.control_messages
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize(
    "text, memory, history",
    [
        pytest.param("我喜欢喝绿茶。", None, [], id="ordinary-preference"),
        pytest.param("把‘记住我喜欢喝绿茶’翻译成英文。", None, [], id="quoted-memory"),
        pytest.param("不要记住我喜欢喝绿茶。", None, [], id="negated-memory"),
        pytest.param("如果我说记住这个口味，你会怎么办？", None, [], id="hypothetical-memory"),
        pytest.param("这个故事让我记住了主角。", None, [], id="ordinary-mention"),
        pytest.param("昨天我让你记住喜欢喝绿茶，你还记得吗？", None, [], id="historical-memory-request"),
        pytest.param("记住我喜欢喝绿茶。", None, [], id="model-result-over-keyword"),
        pytest.param(
            "帮我把刚才那个口味偏好记下来。", "我喜欢喝绿茶", MEMORY_CONTEXT, id="contextual-memory"
        ),
    ],
)
async def test_only_model_memory_decision_is_awaited_once_before_reply(
    monkeypatch, streaming, text, memory, history
):
    service = SamplingService("keep", "off", memory=memory)
    settings = Settings()
    answer, events = await converse(
        monkeypatch, service, settings, text, True, streaming, history, remember=True
    )
    expected = [] if memory is None else [memory]
    assert service.saved_memory == expected
    assert [value for kind, value in events if kind == "memory"] == expected
    assert service.body_memory_counts and set(service.body_memory_counts) == {len(expected)}
    if memory is None:
        assert service.authorization_messages == [], "初始判断不保存时不需要额外复核"
    else:
        assert len(service.authorization_messages) == 1
        assert service.authorization_temperatures == [0.0]
        assert service.authorization_messages[0][-1]["content"][0]["text"] == text
        assert service.authorization_messages[0][1:1 + len(history)] == history
    assert_sampling_and_delivery(service, settings, answer, events, [], streaming)
    assert any(
        messages[-1]["content"][0]["text"] == text and messages[1:1 + len(history)] == history
        for messages in service.control_messages
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
async def test_unclear_model_memory_decision_asks_for_confirmation_without_saving(monkeypatch, streaming):
    service = SamplingService("keep", "off", memory_intent="clarify", body="已经记下来了。")
    settings = Settings()
    answer, events = await converse(
        monkeypatch, service, settings, "地重我喜欢喝绿茶", True, streaming, [], remember=True
    )
    assert service.authorization_messages == []
    assert_confirmation_delivery(service, answer, events, [], streaming)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize("voice, changes", [("keep", []), ("off", [False])])
async def test_memory_review_disagreement_never_saves_or_changes_speech_decision(
    monkeypatch, streaming, voice, changes
):
    service = SamplingService(voice, "on", memory="我喜欢喝绿茶", authorization="none", body="已经记下来了。")
    settings = Settings()
    answer, events = await converse(
        monkeypatch, service, settings, "店主我喜欢喝绿茶", True, streaming, [], remember=True
    )
    assert service.authorization_temperatures == [0.0]
    assert len(service.authorization_messages) == 1
    assert service.authorization_messages[0][-1]["content"][0]["text"] == "店主我喜欢喝绿茶"
    assert_confirmation_delivery(service, answer, events, changes, streaming)
