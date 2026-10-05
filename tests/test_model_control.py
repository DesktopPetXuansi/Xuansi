"""无效执行计划不触发副作用，也不把模型私密正文写入错误或日志。"""

import json
import logging

import httpx
import pytest

from pet.config import Settings
from pet.inference import LocalEngine
from pet.memory import MemoryStore
from pet.speech_control import ControlCallbacks


@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [
    {"voice": "toggle"},
    {"motion": "raise_hand"},
    {"memory_intent": "none", "memory": "测试私密正文"},
    {"memory_intent": "clarify", "memory": "测试私密正文"},
    {"memory_intent": "save", "memory": None},
    {"memory_intent": "save", "memory": "测试私密正文" * 200},
])
async def test_invalid_plan_never_changes_speech_motion_or_saved_memory(monkeypatch, tmp_path, caplog, patch):
    memory = MemoryStore(tmp_path / "memory.json")
    changes, motions = [], []

    async def remember(note):
        memory.remember(note)

    async def handle(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        decision = {"memory_intent": "none", "voice": "keep", "motion": "none", "memory": None, **patch}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(decision)}}]})

    async def start(_):
        pass

    engine = LocalEngine()
    monkeypatch.setattr(engine, "start", start)
    caplog.set_level(logging.INFO)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://127.0.0.1") as client:
        engine.client = client
        with pytest.raises(RuntimeError, match="执行意图") as error:
            await engine.chat(
                Settings(), "处理这次请求", [], [],
                on_speech=ControlCallbacks(changes.append, motions.append, ("blink",), remember),
            )
    assert not changes and not motions and not memory.path.exists()
    assert "测试私密正文" not in str(error.value) + caplog.text
