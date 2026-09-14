"""在后台合成 GIF/WebP/APNG 的处置帧，以 APNG 保留透明度和帧时长。"""

import io
import math

from PIL import Image

MAX_FRAMES = 120
MAX_TOTAL_PIXELS = 12_000_000


def encode_animation(original):
    start = 1 if original.info.get("default_image") else 0
    count = original.n_frames - start
    if count > MAX_FRAMES or original.width * original.height * count > 160_000_000:
        raise ValueError("动图过大，请控制在 120 帧以内并降低分辨率")
    scale = min(
        1, 512 / max(original.size), math.sqrt(MAX_TOTAL_PIXELS / (original.width * original.height * count))
    )
    size = tuple(max(1, int(value * scale)) for value in original.size)
    frames, durations = [], []
    visible, transparent = False, False
    for index in range(start, original.n_frames):
        # Pillow 的 seek/load 已根据 disposal/blend 合成当前完整画布，避免拖影。
        original.seek(index)
        frame = original.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
        frame.info.clear()
        low, high = frame.getchannel("A").getextrema()
        visible |= high >= 128
        transparent |= low < 255
        frames.append(frame)
        durations.append(max(20, min(10000, round(original.info.get("duration", 100) or 100))))
    if not visible:
        raise ValueError("动图完全透明或过淡，无法作为可点击的桌宠")
    encoded = io.BytesIO()
    frames[0].save(
        encoded,
        format="PNG",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        disposal=0,
        blend=0,
    )
    return encoded.getvalue(), size, transparent, count
