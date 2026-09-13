"""按用户明确授权，本地清除生成图中的棋盘格；仅用于这张指定角色素材。"""

import argparse
import logging
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

LOG = logging.getLogger(__name__)


def remove_checker(source):
    image = Image.open(source).convert("RGB")
    pixels = np.asarray(image).astype(np.int16)
    low, high = pixels.min(axis=2), pixels.max(axis=2)
    # 这张素材的底色是中性灰白棋盘；保留肤色、金色和深色发丝。
    candidates = (low >= 140) & (high - low <= 20)
    mask = Image.fromarray((candidates * 255).astype(np.uint8))
    padded = ImageOps.expand(mask, border=1, fill=255)
    ImageDraw.floodfill(padded, (0, 0), 128)
    background = np.asarray(padded)[1:-1, 1:-1] == 128
    remaining = candidates & ~background
    height, width = remaining.shape
    # 发丝闭环中的底色无法从边缘漫水到达；只移除同时含灰、白格子的连通区域。
    for y, x in np.argwhere(remaining):
        if not remaining[y, x]:
            continue
        component = []
        queue = deque([(int(x), int(y))])
        remaining[y, x] = False
        while queue:
            cx, cy = queue.popleft()
            component.append((cy, cx))
            for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                if 0 <= nx < width and 0 <= ny < height and remaining[ny, nx]:
                    remaining[ny, nx] = False
                    queue.append((nx, ny))
        if len(component) >= 60:
            ys, xs = np.array(component).T
            values = low[ys, xs]
            if (values < 220).mean() > 0.08 and (values > 235).mean() > 0.08:
                background[ys, xs] = True
    alpha = Image.fromarray((~background * 255).astype(np.uint8))
    # 半像素羽化，避免在深色桌面上出现锯齿；所有内区仍保持不透明。
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.45))
    result = image.convert("RGBA")
    result.putalpha(alpha)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = remove_checker(args.source)
    args.destination.mkdir(parents=True, exist_ok=True)
    result.save(args.destination / "front.png")
    # 托盘与快捷方式使用头像区域，16px 下比全身更容易辨认。
    icon = result.crop((130, 120, 910, 900))
    icon.save(
        args.destination / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)]
    )
    icon.thumbnail((256, 256), Image.Resampling.LANCZOS)
    icon.save(args.destination / "icon.png")
    LOG.info(
        "角色素材已准备，尺寸=%sx%s，带 alpha=%s",
        *result.size,
        result.getchannel("A").getextrema() == (0, 255),
    )


if __name__ == "__main__":
    main()
