"""新表情协议只发给匹配已验证资源的当前模型。"""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from pet.ai import local_candidates
from pet.ai.providers import create_provider
from pet.ai.providers.base import ProviderError
from pet.ai.selection import Candidate, InferenceRouter
from pet.ai.settings import AISettings, ModelProfile
from pet.config import Settings
from pet.reply_presentation import PRESENTATION_PROMPT, presentation_tool
from pet.tool_protocol import AssistantReply, ToolCall


def test_only_matching_catalog_files_enable_local_presentation(tmp_path, monkeypatch):
    model = SimpleNamespace(verification="verified", model_path="9b/model.gguf", projector_path="9b/mmproj.gguf",
                            resources=("9b-weights", "9b-projector"))
    monkeypatch.setitem(local_candidates.MODELS, "qwen3.5-9b", model)
    monkeypatch.setitem(local_candidates.RESOURCES, "9b-weights", SimpleNamespace(bytes=2))
    monkeypatch.setitem(local_candidates.RESOURCES, "9b-projector", SimpleNamespace(bytes=3))
    folder = tmp_path / "9b"
    folder.mkdir()
    weights, projector = folder / "model.gguf", folder / "mmproj.gguf"
    weights.write_bytes(b"ab")
    projector.write_bytes(b"abc")
    settings = Settings(model_path=str(weights), projector_path=str(projector))
    settings = replace(settings, ai=replace(settings.ai, model_dir=str(tmp_path)))
    candidate = local_candidates.prepared_local_candidates(settings, model_root=tmp_path)[0]
    assert candidate.presentation_verified

    weights.write_bytes(b"different")
    monkeypatch.setattr(local_candidates, "user_model_dir", lambda: tmp_path)
    monkeypatch.setattr(local_candidates, "LEGACY_MODEL_DIR", tmp_path)
    assert not local_candidates.prepared_local_candidates(settings, model_root=tmp_path)
    custom = tmp_path / "custom.gguf"
    custom.write_bytes(b"ab")
    settings = replace(settings, model_path=str(custom))
    assert not local_candidates.prepared_local_candidates(settings, model_root=tmp_path)[0].presentation_verified


def test_router_filters_presentation_after_switching_to_unverified_candidate():
    settings = Settings()
    router = InferenceRouter(local=object(), local_candidates=lambda _: (), provider_factory=lambda _: object())
    tool = presentation_tool()
    router._candidate = Candidate("known", settings, presentation_verified=True)
    assert router.filter_tools(settings, [tool]) == [tool]
    router._candidate = Candidate("fallback", settings)
    assert router.filter_tools(settings, [tool]) == []


@pytest.mark.asyncio
async def test_fallback_provider_does_not_receive_unavailable_presentation_instructions():
    requests = []

    class FakeProvider:
        def __init__(self, fail=False):
            self.fail = fail
            self.stats = {}

        async def start(self, _settings):
            pass

        async def stop(self):
            pass

        async def complete(self, _settings, messages, tools, **_kwargs):
            requests.append((messages, tools))
            if self.fail:
                raise ProviderError("resource", "合成资源不足")
            return AssistantReply("普通回复")

    profile = ModelProfile(endpoint="https://example.test/v1", model="synthetic", credential_ref="test")
    profile = replace(profile, verified_at="now", verification_fingerprint=profile.fingerprint(),
                      verified_capabilities=("text", "image", "tools", "stream", "cancel"))
    settings = replace(Settings(), ai=AISettings(policy="local_first", profile=profile))
    router = InferenceRouter(
        local=FakeProvider(fail=True),
        local_candidates=lambda value: (Candidate("known", value, presentation_verified=True),),
        provider_factory=lambda _: FakeProvider(),
    )
    await router.begin_turn(settings)
    await router.complete(settings, [{"role": "system", "content": "原有提示" + PRESENTATION_PROMPT}],
                          [presentation_tool()])

    assert requests[0][0][0]["content"].endswith(PRESENTATION_PROMPT)
    assert requests[1][0][0]["content"] == "原有提示"
    assert not requests[1][1]


@pytest.mark.parametrize("provider_name", ["custom", "claude", "gemini"])
def test_presentation_history_remains_paired_when_next_turn_uses_another_provider(provider_name):
    """只验证本地消息转换；不宣称未经配置的在线服务已联网验收。"""
    profile = ModelProfile(provider=provider_name, endpoint="https://synthetic.test/v1", model="synthetic")
    provider = create_provider(profile, key="synthetic")
    call = ToolCall("present-1", "present_reply", '{"text":"你好","expression":"happy"}')
    history = [
        {"role": "user", "content": "你好"},
        AssistantReply("", (call,), "tool_calls").message(),
        {"role": "tool", "tool_call_id": call.id, "content": '{"ok": true, "status": "presented"}'},
        {"role": "assistant", "content": "你好"},
        {"role": "user", "content": "继续"},
    ]
    if provider_name == "custom":
        converted = provider.messages(history)
        assert [item["role"] for item in converted] == ["user", "assistant", "tool", "assistant", "user"]
        assert converted[2]["tool_call_id"] == "present-1"
    elif provider_name == "claude":
        _, converted = provider.messages(history)
        assert [item["role"] for item in converted] == ["user", "assistant", "user", "assistant", "user"]
        assert converted[1]["content"][0]["id"] == converted[2]["content"][0]["tool_use_id"] == "present-1"
    else:
        converted = provider.payload(history, [])["contents"]
        assert [item["role"] for item in converted] == ["user", "model", "user", "model", "user"]
        assert converted[1]["parts"][0]["functionCall"]["name"] == "present_reply"
        assert converted[2]["parts"][0]["functionResponse"]["name"] == "present_reply"
