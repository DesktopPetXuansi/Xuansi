"""真实本机协议探针；只用合成文字和图片，不访问用户数据或执行操作。"""

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import sys
import time
from dataclasses import replace
from io import BytesIO
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.config import Settings
from pet.inference import LocalEngine

LOG = logging.getLogger(__name__)
TOOLS = [{"type": "function", "function": {
    "name": "inspect_fixture", "description": "读取本次测试合成资料，返回图片或校验值。",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}}]


async def verify(output, gpu_layers):
    engine = LocalEngine()
    report = {"passed": False, "checks": [], "input": "仅合成资料"}
    settings = replace(Settings(), observe=False, gpu_layers=gpu_layers)
    started = time.monotonic()

    async def request(messages, choice="auto", stream=False):
        payload = {
            "model": "local-pet", "messages": messages, "tools": TOOLS,
            "tool_choice": choice, "parallel_tool_calls": False,
            "max_tokens": 256, "temperature": 0.7,
            "chat_template_kwargs": {"enable_thinking": False}, "stream": stream,
        }
        response = await engine.client.post("/v1/chat/completions/input_tokens", json=payload)
        response.raise_for_status()
        count = response.json()["input_tokens"]
        report["input_tokens"] = count
        response = await engine.client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        return response

    def check(label, passed, actual=None):
        report["checks"].append({"case": label, "passed": passed, "actual": actual})
        LOG.info("协议探针 case=%s passed=%s", label, passed)
        if not passed:
            raise AssertionError(label)

    try:
        await engine.start(settings)
        props = (await engine.client.get("/props")).json()
        template = str(props.get("chat_template", ""))
        report["template_sha256"] = hashlib.sha256(template.encode()).hexdigest()
        system = {"role": "system", "content": "你是测试助手。需要资料时调用工具；按工具真实结果回答。"}
        plain = (await request([system, {"role": "user", "content": "你好，请只说一句问候。"}])).json()
        plain_choice = plain["choices"][0]
        check("auto普通直答", plain_choice["finish_reason"] == "stop"
              and not plain_choice["message"].get("tool_calls"), plain_choice)
        messages = [system, {"role": "user", "content": "请使用inspect_fixture读取测试资料，再告诉我结果。"}]
        result = (await request(messages)).json()["choices"][0]
        calls = result["message"].get("tool_calls", [])
        check("auto原生工具选择", result["finish_reason"] == "tool_calls"
              and len(calls) == 1 and calls[0]["function"]["name"] == "inspect_fixture", result)
        messages.append(result["message"])
        messages.append({"role": "tool", "tool_call_id": calls[0]["id"],
                         "content": json.dumps({"value": "fixture-731"}, ensure_ascii=False)})
        final = (await request(messages, "none")).json()["choices"][0]
        check("工具结果续答", "fixture-731" in (final["message"].get("content") or ""), final)
        required = (await request([system, {"role": "user", "content": "读取资料。"}], "required")).json()
        check("required结构", bool(required["choices"][0]["message"].get("tool_calls")), required)
        none = (await request([system, {"role": "user", "content": "读取资料。"}], "none")).json()
        check("none禁止调用", not none["choices"][0]["message"].get("tool_calls"), none)
        image = BytesIO()
        Image.new("RGB", (96, 96), "blue").save(image, "JPEG")
        image_content = [
            {"type": "text", "text": "这是工具返回的合成图片资料，只回答图片是什么颜色。"},
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(image.getvalue()).decode("ascii")}},
        ]
        image_messages = [system, {"role": "user", "content": "读取工具的图片，告诉我颜色。"},
                          result["message"], {"role": "tool", "tool_call_id": calls[0]["id"],
                                              "content": image_content}]
        visual = (await request(image_messages, "none")).json()["choices"][0]
        check("tool角色图片回传续答", "蓝" in (visual["message"].get("content") or ""), visual)
        streamed = await request([system, {"role": "user", "content": "请用工具读取测试资料。"}], stream=True)
        deltas = [json.loads(line[6:]) for line in streamed.text.splitlines()
                  if line.startswith("data: ") and line != "data: [DONE]"]
        tool_deltas = [item["choices"][0]["delta"]["tool_calls"] for item in deltas
                       if item.get("choices") and item["choices"][0]["delta"].get("tool_calls")]
        check("流式原生工具差量", bool(tool_deltas), tool_deltas)
        report["passed"] = True
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        LOG.exception("协议探针未通过")
    finally:
        await engine.stop()
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]),
                      "output": str(output)}, ensure_ascii=False))
    return int(not report["passed"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu-layers", type=int, default=20)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(asyncio.run(verify(args.output, args.gpu_layers)))
