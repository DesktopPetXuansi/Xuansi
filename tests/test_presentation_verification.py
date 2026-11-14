"""真实模型验收须区分纯展示输出与用户明确禁止的工具调用。"""

import importlib
from pathlib import Path
from types import SimpleNamespace

from pet.tool_protocol import AssistantReply


def test_direct_reply_allows_presentation_but_literal_no_tools_rejects_it(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    verification = importlib.import_module("verify_tool_dialogue")
    item = {
        "calls": [{"name": "present_reply"}], "tool_results": [],
        "completion_requests": 1, "visible_text": ["无需回应"],
    }
    runtime = SimpleNamespace(history=[])
    final = AssistantReply("无需回应")
    direct = verification.score(SimpleNamespace(expected="direct", kind="chat"), item, runtime, final)
    literal = verification.score(SimpleNamespace(expected="literal", kind="chat"), item, runtime, final)

    assert all(direct.values())
    assert not literal["no_tools"]
