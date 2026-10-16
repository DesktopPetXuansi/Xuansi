"""真实模型评分也需识别错误事实，不能把工具成功当作用户事项保存正确。"""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from pet.memory import MemoryStore
from pet.tool_protocol import AssistantReply


@pytest.mark.parametrize("saved, should_pass", [
    ("玄司最喜欢乌龙茶", False),
    ("用户最喜欢乌龙茶", True),
    ("我最喜欢乌龙茶", True),
])
def test_memory_score_rejects_assistant_attribution(tmp_path, monkeypatch, saved, should_pass):
    """工具和磁盘都成功时，错误人物仍必须让验收失败；原报告不被改写。"""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    verification = importlib.import_module("verify_tool_dialogue")
    store = MemoryStore(tmp_path / "memory.json")
    store.save(saved)
    case = SimpleNamespace(expected="save_memory", kind="chat",
                           memory_contains=("乌龙茶",), memory_excludes=("玄司",))
    item = {"calls": [{"name": "save_memory"}], "tool_results": [{
        "name": "save_memory", "message": {"content": '{"ok": true}'},
    }]}

    checks = verification.score(case, item, SimpleNamespace(memory=store), AssistantReply("已记住。"))

    assert all(checks.values()) is should_pass
