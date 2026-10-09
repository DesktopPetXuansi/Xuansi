"""无效执行计划不触发副作用，也不把模型私密正文写入错误或日志。"""

import json
import logging

import httpx
import pytest

from pet.config import Settings
from pet.inference import LocalEngine
from pet.memory import MemoryStore
from pet.model_control import control_prompt, decide_control
from pet.speech_control import ControlCallbacks


@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [
    {"voice": "toggle"},
    {"tts": "guess"},
    {"motion": "raise_hand"},
    {"memory_intent": "none", "memory": "测试私密正文"},
    {"memory_intent": "clarify", "memory": "测试私密正文"},
    {"memory_intent": "save", "memory": None},
    {"memory_intent": "save", "memory": "测试私密正文" * 200},
])
async def test_invalid_plan_never_changes_speech_motion_or_saved_memory(monkeypatch, tmp_path, caplog, patch):
    memory = MemoryStore(tmp_path / "memory.json")
    changes, motions, voices = [], [], []

    async def remember(note):
        memory.remember(note)

    async def handle(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        decision = {"memory_intent": "none", "voice": "keep", "motion": "none", "memory": None,
                    "tts": "fast", **patch}
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
                on_speech=ControlCallbacks(changes.append, motions.append, ("blink",), remember, voices.append),
            )
    assert not changes and not motions and not voices and not memory.path.exists()
    assert "测试私密正文" not in str(error.value) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("question, selected", [
    ("请把你好翻译成英文，只给译文", "natural"),
    ("Please answer in Chinese: how are you?", "fast"),
])
async def test_tts_uses_model_answer_language_instead_of_input_language(question, selected):
    async def handle(request):
        payload = json.loads(request.content)
        assert "即将生成的回复" in payload["messages"][0]["content"]
        assert "tts" in payload["grammar"]
        assert payload["max_tokens"] >= 96
        decision = {"memory_intent": "none", "voice": "keep", "motion": "none",
                    "memory": None, "tts": selected}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(decision)}}]})

    messages = [{"role": "system", "content": control_prompt(True, (), False)},
                {"role": "user", "content": question}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://127.0.0.1") as client:
        decision = await decide_control(client, messages, (), False)
    assert decision.tts == selected


@pytest.mark.asyncio
async def test_explicit_natural_choice_is_not_overridden_by_model():
    async def handle(_request):
        decision = {"memory_intent": "none", "voice": "keep", "motion": "none",
                    "memory": None, "tts": "fast"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(decision)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://127.0.0.1") as client:
        with pytest.raises(RuntimeError, match="执行意图"):
            await decide_control(client, [], (), False, requested_tts="natural")
