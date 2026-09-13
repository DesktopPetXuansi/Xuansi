"""用虚拟图片验证真实本地推理、鉴权、取消和显存，不使用用户画面。"""

import asyncio
import json
import sys
import time
from io import BytesIO
from pathlib import Path

import httpx
import psutil
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.config import ROOT, Settings
from pet.inference import LocalEngine


async def main():
    output = ROOT / "data/verification"
    output.mkdir(parents=True, exist_ok=True)
    # 保留旧标记遮字的失败证据，使用按钮空白处重新验证。
    previous = output / "inference-report.json"
    baseline = output / "inference-occluded-baseline.json"
    if previous.exists() and not baseline.exists():
        baseline.write_bytes(previous.read_bytes())
        (output / "vision-occluded-baseline.png").write_bytes((output / "vision-fixture.png").read_bytes())
    picture = Image.new("RGB", (640, 448), "#f8faf5")
    draw = ImageDraw.Draw(picture)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 28)
    draw.text((42, 35), "文件整理工具", font=font, fill="#23442f")
    draw.text((42, 130), "待处理文件：3", font=font, fill="#23442f")
    draw.rounded_rectangle((170, 280, 440, 354), 9, fill="#507758")
    draw.text((243, 295), "开始整理", font=font, fill="white")
    draw.ellipse((386, 307, 410, 331), outline="red", width=3)
    picture.save(output / "vision-fixture.png")
    stream = BytesIO()
    picture.save(stream, format="JPEG", quality=90)
    engine = LocalEngine()
    report = {}
    try:
        t = time.monotonic()
        report["vision_reply"] = await engine.chat(
            Settings(),
            "红圈标记了哪个按钮？待处理文件有几个？只回答按钮名称和数字。",
            [stream.getvalue()],
            [],
        )
        report["vision_seconds_including_load"] = round(time.monotonic() - t, 2)
        report["vision_expected"] = "开始整理；3"
        report["vision_matches_baseline"] = (
            "开始整理" in report["vision_reply"] and "3" in report["vision_reply"]
        )
        report["pid"] = engine.process.pid
        async with httpx.AsyncClient(trust_env=False) as outsider:
            denied = await outsider.get(engine.client.base_url.join("/v1/models"))
            report["unauthenticated_status"] = denied.status_code
        t = time.monotonic()
        report["persona_reply"] = await engine.chat(
            Settings(name="团子", persona="你的名字是团子。用户喜欢简短的中文回答。"),
            "你叫什么名字？我喜欢什么样的回答？",
            [],
            [],
        )
        report["warm_text_seconds"] = round(time.monotonic() - t, 2)
        process = psutil.Process(engine.process.pid)
        report["model_rss_mb"] = round(process.memory_info().rss / 2**20)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        pid = engine.process.pid
        task = asyncio.create_task(engine.chat(Settings(), "请详细列举一百种动物，并逐项介绍。", [], []))
        await asyncio.sleep(0.8)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        report["cancel_released_process"] = not psutil.pid_exists(pid)
    finally:
        await engine.stop()
        (output / "inference-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
