"""用受控本地 HTTP 响应验证模型动作先于正文交付，且请求含状态及格式约束。"""

import json

import httpx
import pytest

from pet.config import Settings
from pet.inference import LocalEngine


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
async def test_model_directive_precedes_body_and_is_absent_from_answer(monkeypatch, streaming):
    events = []

    async def handle(request):
        payload = json.loads(request.content)
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        assert payload["grammar"].startswith("root ::=")
        assert "当前对话朗读：开启" in payload["messages"][0]["content"]
        assert payload["messages"][-1]["content"][0]["text"] == "我需要专心写完这封邮件"
        if not streaming:
            return httpx.Response(200, json={"choices": [{"message": {
                "content": "[voice:off]\n好的，我安静陪你。"
            }}]})
        chunks = ["[voi", "ce:o", "ff]\n好的，", "我安静陪你。"]
        lines = ["data: " + json.dumps({"choices": [{"delta": {"content": chunk}}]}) + "\n\n"
                 for chunk in chunks]
        return httpx.Response(200, text="".join(lines) + "data: [DONE]\n\n")

    async def start(_):
        pass

    async def chunk(text):
        events.append(("text", text))

    engine = LocalEngine()
    monkeypatch.setattr(engine, "start", start)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://127.0.0.1") as client:
        engine.client = client
        answer = await engine.chat(
            Settings(), "我需要专心写完这封邮件", [], [],
            on_chunk=chunk if streaming else None,
            on_speech=lambda enabled: events.append(("speech", enabled)), speech_enabled=True,
        )
    assert events[0] == ("speech", False)
    assert answer == "好的，我安静陪你。"
    if streaming:
        assert "".join(text for kind, text in events if kind == "text") == answer
