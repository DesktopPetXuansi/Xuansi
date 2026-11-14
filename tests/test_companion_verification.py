"""断点续跑只复用相同实验的完整场景，不启动真实模型。"""

import json
from types import SimpleNamespace

import pytest

from scripts import verify_companion_dialogue as verification


@pytest.mark.asyncio
async def test_interrupted_comparison_resumes_only_matching_finished_cases(tmp_path, monkeypatch):
    output = tmp_path / "report.json"
    calls = []

    class Engine:
        async def stop(self):
            pass

    async def dialogue(_runtime, _epoch, _settings, text, *_args):
        calls.append(text)
        return SimpleNamespace(content="合成回复")

    monkeypatch.setattr(verification.psutil, "process_iter", lambda *_args: ())
    monkeypatch.setattr(verification, "create_inference_router", Engine)
    monkeypatch.setattr(verification, "CASES", (("first", ["一"]), ("second", ["二"])))
    monkeypatch.setattr(verification.tool_dialogue, "run_dialogue", dialogue)
    assert await verification.run(output)
    assert calls == ["一", "一", "二", "二"]

    report = json.loads(output.read_text(encoding="utf-8"))
    report["cases"].pop()
    report["completed"] = False
    verification.save_report(output, report)
    calls.clear()
    assert await verification.run(output, resume=True)
    assert calls == ["二", "二"]

    monkeypatch.setattr(verification, "CASES", (("changed", ["一"]),))
    with pytest.raises(ValueError, match="不能混合续跑"):
        await verification.run(output, resume=True)
