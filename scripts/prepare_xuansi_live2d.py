"""按玄司原图的实际坐标拆层，供 Cubism 绑定；绝不覆盖原 PNG。

依赖：Pillow、numpy 和 requirements-rigging.lock.txt（仅素材制作，不是桌宠运行依赖）。
用户已明确授权本机脚本拆层和组装 PSD。补绘只取生成参考的眼嘴区域。
"""

import hashlib
import json
import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from psd_tools import PSDImage
from psd_tools.api.layers import PixelLayer

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets/xuansi/rigging"
LOG = logging.getLogger("xuansi.layers")
SIZE = (1024, 1536)


def polygon(points, feather=0):
    mask = Image.new("L", SIZE)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(feather)) if feather else mask


def extract(image, mask):
    result = image.copy()
    alpha = np.minimum(np.asarray(image.getchannel("A")), np.asarray(mask))
    result.putalpha(Image.fromarray(alpha))
    pixels = np.asarray(result).copy()
    pixels[alpha == 0, :3] = 0
    return Image.fromarray(pixels)


def overlay(image, replacement, mask):
    # 参考图的面部是实体区域，不继承生成器在皮肤上的半透明噪声。
    replacement = replacement.copy()
    replacement.putalpha(mask)
    return Image.alpha_composite(image, replacement)


def eye_layers(source, points, iris_points):
    mask = polygon(points, 1.0)
    iris_mask = polygon(iris_points, .6)
    iris = extract(source, iris_mask)
    bounds = iris_mask.getbbox()
    y = np.arange(SIZE[1])[:, None, None]
    amount = np.clip((y - bounds[1]) / (bounds[3] - bounds[1]), 0, 1)
    upper, lower = np.array([116, 102, 99]), np.array([250, 243, 235])
    colors = np.broadcast_to(upper * (1 - amount) + lower * amount, (1536, 1024, 3))
    white = Image.fromarray(colors.astype(np.uint8)).convert("RGBA")
    # 虹膜底下补眼白。虹膜保持原像素，轻微移动时不会留下原虹膜的残影。
    white = overlay(source, white, iris_mask)
    return extract(white, mask), iris, mask


def build():
    source_path = OUTPUT.parent / "front.png"
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    original = Image.open(source_path).convert("RGBA")
    reference = Image.open(OUTPUT / "blink-mouth-reference.png").convert("RGBA")
    if original.size != SIZE or reference.size != SIZE:
        raise ValueError("坐标针对 1024×1536 玄司立绘；尺寸变化需重新校准")
    original_alpha = np.asarray(original.getchannel("A"))
    # 仅修复脸部内侧的透明孔洞；保持原图 RGB 和轮廓不变。
    interior = polygon([(295,566),(574,535),(612,583),(587,676),(471,726),(330,706),(286,644)])
    fixed_alpha = np.maximum(original_alpha, np.asarray(interior))
    source = original.copy()
    source.putalpha(Image.fromarray(fixed_alpha))
    body_mask = polygon([(0,1536),(0,915),(214,907),(269,856),(305,795),
                         (397,755),(415,742),(498,735),(517,761),(570,779),
                         (615,806),(635,887),(679,928),(704,978),(696,1116),
                         (840,1284),(900,1536)])
    head_mask = Image.fromarray(255 - np.asarray(body_mask))
    eyes = {
        "L": ([(482,584),(498,559),(529,543),(571,538),(612,543),(635,546),
               (616,563),(608,605),(584,630),(531,639),(495,625)],
              [(512,572),(532,561),(557,558),(577,562),(588,580),(582,607),
               (568,623),(546,629),(525,620),(515,603)]),
        "R": ([(267,569),(287,565),(324,568),(354,580),(381,602),(389,623),
               (378,646),(348,657),(307,657),(280,641),(275,611)],
              [(299,597),(314,588),(337,588),(357,598),(370,619),(367,641),
               (351,649),(327,648),(310,633),(302,615)]),
    }
    plate = source.copy()
    eye_images = {}
    for side, (outline, iris) in eyes.items():
        white, eyeball, mask = eye_layers(source, outline, iris)
        # 闭眼补绘作底板；睁眼层完全覆盖它，默认表情还原原立绘。
        plate = overlay(plate, reference, mask)
        eye_images[side] = (white, eyeball)
    mouth_mask = polygon([(416,676),(437,672),(459,676),(469,691),
                          (461,713),(433,718),(414,705)], 2)
    mouth_closed = extract(source, mouth_mask)
    mouth_open = extract(reference, mouth_mask)
    mouth_open.putalpha(mouth_mask)
    # 闭嘴底色从嘴周皮肤取样，避免开口层缩小时露出两张嘴。
    skin = source.crop((410,659,476,680)).resize((66,53), Image.Resampling.BICUBIC)
    blank = source.copy()
    blank.paste(skin, (410,668))
    plate = overlay(plate, blank, mouth_mask)
    layers = [
        ("Body", extract(source, body_mask), True),
        ("HeadBase", extract(plate, head_mask), True),
        ("EyeWhiteL", eye_images["L"][0], True),
        ("EyeBallL", eye_images["L"][1], True),
        ("EyeWhiteR", eye_images["R"][0], True),
        ("EyeBallR", eye_images["R"][1], True),
        ("MouthOpen", mouth_open, False),
        ("MouthClosed", mouth_closed, True),
    ]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    layer_directory = OUTPUT / "layers"
    layer_directory.mkdir(exist_ok=True)
    psd = PSDImage.new("RGB", SIZE, color=(255, 255, 255))
    composite = Image.new("RGBA", SIZE)
    metadata = []
    for name, pixels, visible in layers:
        pixels.save(layer_directory / f"{name}.png")
        bounds = pixels.getchannel("A").getbbox()
        layer = PixelLayer.frompil(pixels.crop(bounds), psd, name=name,
                                   left=bounds[0], top=bounds[1])
        layer.visible = visible
        if visible:
            composite = Image.alpha_composite(composite, pixels)
        metadata.append({"name": name, "bounds": bounds, "visible": visible})
        LOG.info("图层 %s bbox=%s visible=%s", name, bounds, visible)
    psd.save(OUTPUT / "xuansi-layers.psd")
    composite.save(OUTPUT / "neutral-preview.png")
    blink = Image.alpha_composite(layers[0][1], layers[1][1])
    blink = Image.alpha_composite(blink, mouth_open)
    blink.save(OUTPUT / "blink-talk-preview.png")
    manifest = {"source_sha256": digest, "size": SIZE, "layers": metadata,
                "repaired_alpha_pixels": int(np.count_nonzero(fixed_alpha != original_alpha)),
                "note": "分层素材来自原图；参数与关键形保存在 xuansi.cmo3 和 moc3，PSD 本身不含运行时绑定。"}
    (OUTPUT / "layers.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    # 独立复读 PSD，验证尺寸、层数、名称和像素数据均可读取。
    restored = PSDImage.open(OUTPUT / "xuansi-layers.psd")
    assert restored.size == SIZE and len(restored) == len(layers)
    assert [layer.name for layer in restored] == [name for name, _, _ in layers]
    assert all(layer.topil() is not None for layer in restored)
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == digest
    LOG.info("PSD 复读通过；原 PNG SHA256 未改变：%s", digest)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    build()
