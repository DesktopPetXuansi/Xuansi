"""生成可重复编辑的透明火柴人分层、纹理图集和循环挥手动画。"""

import json
import logging
from pathlib import Path

from PIL import Image, ImageDraw
from psd_tools import PSDImage
from psd_tools.api.layers import PixelLayer

ROOT = Path(__file__).resolve().parents[1]
CANVAS = (512, 768)
ATLAS = (512, 512)
SCALE = 4
COLOR = (32, 36, 43, 255)
PIVOT = (343, 287)
LOGGER = logging.getLogger("火柴人素材")


def stroke(draw, points, width=12):
    """使用圆形端点和高分辨率绘制，保持线条平滑。"""
    scaled = [(x * SCALE, y * SCALE) for x, y in points]
    draw.line(scaled, fill=COLOR, width=width * SCALE, joint="curve")
    radius = width * SCALE / 2
    for x, y in scaled:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=COLOR)


def draw_layer(name):
    """各肢体独立绘制，前臂和手共用一个可旋转网格。"""
    image = Image.new("RGBA", (CANVAS[0] * SCALE, CANVAS[1] * SCALE))
    draw = ImageDraw.Draw(image)
    if name == "Head":
        draw.ellipse(tuple(v * SCALE for v in (159, 92, 281, 214)), outline=COLOR, width=12 * SCALE)
        for x in (202, 238):
            draw.ellipse(tuple(v * SCALE for v in (x - 4, 144, x + 4, 152)), fill=COLOR)
        draw.arc(tuple(v * SCALE for v in (199, 145, 241, 181)), 25, 155, fill=COLOR, width=5 * SCALE)
    elif name == "Body":
        stroke(draw, [(220, 215), (220, 459)])
    elif name == "ArmLeft":
        stroke(draw, [(220, 290), (153, 349), (136, 431)])
    elif name == "LegLeft":
        stroke(draw, [(220, 459), (154, 690), (137, 690)])
    elif name == "LegRight":
        stroke(draw, [(220, 459), (292, 690), (309, 690)])
    elif name == "ArmRightUpper":
        stroke(draw, [(220, 290), (343, 287)])
    elif name == "ArmRightForearm":
        stroke(draw, [(343, 287), (349, 177)])
        stroke(draw, [(349, 177), (350, 162), (352, 133)], 8)
        stroke(draw, [(350, 162), (362, 158), (365, 125)], 8)
        stroke(draw, [(362, 158), (373, 163), (378, 135)], 8)
        stroke(draw, [(373, 163), (382, 171), (388, 149)], 8)
        stroke(draw, [(382, 171), (370, 184), (349, 177)], 8)
        stroke(draw, [(349, 177), (336, 163)], 8)
    return image.resize(CANVAS, Image.Resampling.LANCZOS)


def save_json(path, data):
    """保持 JSON 可人工审核且统一使用 UTF-8。"""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pack_atlas(layers):
    """按高度降序逐行排布，裁切边界保留四像素透明间距。"""
    atlas = Image.new("RGBA", ATLAS)
    records = []
    cursor_x = cursor_y = row_height = 0
    for name, image in sorted(layers.items(), key=lambda item: item[1].getbbox()[3] - item[1].getbbox()[1], reverse=True):
        bbox = image.getbbox()
        x0, y0, x1, y1 = bbox
        width, height = x1 - x0, y1 - y0
        if cursor_x + width + 8 > ATLAS[0]:
            cursor_y += row_height
            cursor_x = row_height = 0
        if cursor_y + height + 8 > ATLAS[1]:
            raise ValueError("纹理图集空间不足")
        ax, ay = cursor_x + 4, cursor_y + 4
        atlas.alpha_composite(image.crop(bbox), (ax, ay))
        records.append({
            "id": name, "name": name, "bbox": list(bbox),
            "rect": [ax, ay, ax + width, ay + height],
            "vertices": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            "uv": [[ax / 512, ay / 512], [(ax + width) / 512, ay / 512],
                   [(ax + width) / 512, (ay + height) / 512], [ax / 512, (ay + height) / 512]],
            "indices": [0, 1, 2, 0, 2, 3],
            "pivot": list(PIVOT) if name == "ArmRightForearm" else None,
        })
        cursor_x += width + 8
        row_height = max(row_height, height + 8)
    # 恢复绘制顺序，保证网格与源 PSD 的层名关系稳定。
    records.sort(key=lambda record: list(layers).index(record["name"]))
    return atlas, records


def main():
    """仅生成真实素材；编译后的 moc3 由模型绑定流程另行导出。"""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for directory in (ROOT / "source/layers", ROOT / "textures", ROOT / "motions"):
        directory.mkdir(parents=True, exist_ok=True)
    names = ["Head", "Body", "ArmLeft", "LegLeft", "LegRight", "ArmRightUpper", "ArmRightForearm"]
    layers = {name: draw_layer(name) for name in names}
    composite = Image.new("RGBA", CANVAS)
    psd = PSDImage.new("RGBA", CANVAS, color=(0, 0, 0, 0))
    for name, layer in layers.items():
        layer.save(ROOT / f"source/layers/{name}.png")
        composite.alpha_composite(layer)
        PixelLayer.frompil(layer, psd, name=name)
    composite.save(ROOT / "preview-neutral.png")
    psd.save(ROOT / "source/stickman-layers.psd")
    atlas, records = pack_atlas(layers)
    atlas.save(ROOT / "textures/texture_00.png")
    save_json(ROOT / "source/mesh-layout.json", {
        "canvas": list(CANVAS), "atlas": list(ATLAS), "pivot": list(PIVOT),
        "parameter": {"id": "ParamWave", "minimum": -1, "maximum": 1, "default": 0},
        "rotationDegrees": 25, "layers": records,
    })
    # 每半秒一段三次贝塞尔，端点切线水平，首尾位置和速度连续。
    segments = [0, 0]
    values = [0, 1, 0, -1, 0]
    for index in range(4):
        start = index * 0.5
        end = start + 0.5
        segments.extend([1, start + 1 / 6, values[index], end - 1 / 6, values[index + 1], end, values[index + 1]])
    save_json(ROOT / "motions/wave.motion3.json", {
        "Version": 3,
        "Meta": {"Duration": 2, "Fps": 30, "Loop": True, "AreBeziersRestricted": True,
                 "CurveCount": 1, "TotalSegmentCount": 4, "TotalPointCount": 13,
                 "UserDataCount": 0, "TotalUserDataSize": 0},
        "Curves": [{"Target": "Parameter", "Id": "ParamWave", "Segments": segments}],
    })
    save_json(ROOT / "stickman.model3.json", {
        "Version": 3,
        "FileReferences": {"Moc": "stickman.moc3", "Textures": ["textures/texture_00.png"],
                           "DisplayInfo": "stickman.cdi3.json",
                           "Motions": {group: [{"File": "motions/wave.motion3.json", "FadeInTime": 0.1, "FadeOutTime": 0.1}]
                                       for group in ("Idle", "Wave")}},
        "Groups": [], "HitAreas": [],
    })
    save_json(ROOT / "stickman.cdi3.json", {
        "Version": 3, "Parameters": [{"Id": "ParamWave", "GroupId": "", "Name": "循环挥手"}],
        "ParameterGroups": [], "Parts": [],
    })
    for record in records:
        # 从图集还原裁切图，验证 UV、边界、图层内容完全一致。
        original = layers[record["name"]].crop(record["bbox"])
        restored = atlas.crop(record["rect"])
        assert original.tobytes() == restored.tobytes(), "图集与原图内容不一致"
    reopened = PSDImage.open(ROOT / "source/stickman-layers.psd")
    assert len(reopened) == 7 and reopened.size == CANVAS, "PSD 图层或尺寸不正确"
    LOGGER.info("已生成七个透明图层、PSD、512×512 图集及两秒循环挥手动作：%s", ROOT)


if __name__ == "__main__":
    main()
