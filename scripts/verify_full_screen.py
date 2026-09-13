"""人工整屏图片 → 真实捕获编码路径 → 本地图文模型；不读取实际桌面。"""

import asyncio
import json
import sys
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.config import ROOT, Settings
from pet.desktop import capture_screen
from pet.inference import LocalEngine


async def main():
    output = ROOT / "data/verification"
    output.mkdir(parents=True, exist_ok=True)
    source = Image.new("RGB", (2560, 1440), "#f7f8f3")
    draw = ImageDraw.Draw(source)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 72)
    draw.text((80, 100), "文件总数：3", font=font, fill="#293d33")
    draw.text((1770, 1250), "状态：待开始", font=font, fill="#293d33")
    draw.rounded_rectangle((1030, 570, 1530, 820), 20, fill="#497758")
    draw.text((1110, 655), "开始整理", font=font, fill="white")
    requests = []

    class Grabber:
        monitors = [{}, {"left": 0, "top": 0, "width": 2560, "height": 1440}]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def grab(self, bounds):
            requests.append(bounds)
            frame = source.crop(
                (
                    bounds["left"],
                    bounds["top"],
                    bounds["left"] + bounds["width"],
                    bounds["top"] + bounds["height"],
                )
            )
            return SimpleNamespace(size=frame.size, rgb=frame.tobytes())

    started = time.monotonic()
    with patch("pet.desktop.mss.mss", Grabber):
        data = await asyncio.to_thread(capture_screen, 1480, 760, "screen")
    report = {
        "capture_encode_seconds": round(time.monotonic() - started, 3),
        "requested_bounds": requests,
        "encoded_size": Image.open(BytesIO(data)).size,
        "source": "人工生成的 2560x1440 图片，未读取真实桌面",
    }
    (output / "full-screen-fixture.jpg").write_bytes(data)
    engine = LocalEngine()
    try:
        reply = await engine.chat(
            Settings(),
            "请读取整张画面：左上角的文件总数是多少？右下角的状态是什么？只回答这两项。",
            [data],
            [],
        )
        report["reply"] = reply
        report["far_apart_content_recognized"] = "3" in reply and "待开始" in reply
        report["response_seconds_including_load"] = engine.stats["last_response_seconds"]
    finally:
        await engine.stop()
        (output / "full-screen-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=True, indent=2))
    assert report["far_apart_content_recognized"]


if __name__ == "__main__":
    asyncio.run(main())
