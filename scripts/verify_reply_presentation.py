"""用合成本地对话检查表情终结工具；不读取用户配置、记忆或屏幕。"""

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet.config import Settings
from pet.inference import LocalEngine, request_messages
from pet.model_tools import ToolContext
from pet.reply_presentation import PRESENTATION_PROMPT, parse_presentation, presentation_tool
from pet.tool_dialogue import COMPANION_PROMPT, PROMPT

LOG = logging.getLogger(__name__)
CASES = (
    ("tired", "这个项目又报错了，我折腾了一晚上。"),
    ("success", "太好了！我终于把问题解决了。"),
    ("question", "Python 列表和元组有什么区别？"),
    ("praise", "你刚才眨眼的样子真可爱。"),
    ("decline", "先别给我建议，我今天不想继续了。"),
    ("memory", "请记住我喜欢喝绿茶。"),
)


async def verify(output, gpu_layers):
    settings = replace(Settings(), observe=False, gpu_layers=gpu_layers)
    engine = LocalEngine()
    runtime = SimpleNamespace(
        engine=engine, epoch=0, motion_actions=("blink",), should_speak=lambda *_: False,
    )
    context = ToolContext(runtime, 0, settings, "chat", "", None, None)
    tools = [*context.tools(), presentation_tool()]
    report = {"input": "仅合成资料", "cases": [], "passed": False}
    started = time.monotonic()
    try:
        await engine.start(settings)
        for name, text in CASES:
            messages = request_messages(settings, text, [], [])
            messages[0]["content"] += PROMPT + COMPANION_PROMPT + PRESENTATION_PROMPT
            case_started = time.monotonic()
            reply = await engine.complete(settings, messages, tools, tool_choice="auto")
            names = [call.name for call in reply.tool_calls]
            entry = {
                "case": name,
                "calls": names,
                "content": reply.content,
                "elapsed_seconds": round(time.monotonic() - case_started, 3),
            }
            if name == "memory" and names == ["save_memory"]:
                # 此处只检查选择，绝不执行写入，也不接触用户持久记忆。
                entry["text"] = "合成保存请求已选择正确的工具"
            elif name == "memory":
                entry["error"] = "明确要求保存时未选择记忆工具"
            elif len(reply.tool_calls) == 1 and names == ["present_reply"]:
                presented = parse_presentation(reply.tool_calls[0].arguments)
                entry.update(text=presented.text, expression=presented.expression)
            elif not names and reply.content.strip():
                entry.update(text=reply.content, expression="neutral", fallback=True)
            else:
                entry["error"] = "输出为空、混合调用或选择了不符合场景的工具"
            report["cases"].append(entry)
            LOG.info("表情协议探针 case=%s tools=%s", name, ",".join(names) or "none")
        report["passed"] = all("error" not in case for case in report["cases"])
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        LOG.exception("本机表情协议探针失败")
    finally:
        await engine.stop()
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(output.write_text, json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "cases": len(report["cases"]), "output": str(output)},
                     ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu-layers", type=int, default=20)
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(asyncio.run(verify(arguments.output, arguments.gpu_layers)))
