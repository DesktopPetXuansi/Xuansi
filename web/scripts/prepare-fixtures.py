"""仅为本地闭环验收准备资源，不作为官方资源发布或上传第三方。"""

import json
import logging
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "web/.runtime/fixtures"
LOG = logging.getLogger("fixtures")


def prepare():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (64, 64), (76, 101, 78, 220)).save(FIXTURES / "plain.png")
    Image.new("RGB", (3, 2), (76, 101, 78)).save(FIXTURES / "plain.webp", lossless=True)
    frames = [Image.new("RGBA", (32, 32), color) for color in [(76, 101, 78, 255), (101, 78, 76, 255)]]
    frames[0].save(FIXTURES / "plain.gif", save_all=True, append_images=frames[1:], duration=150, loop=0)
    source = ROOT / "assets/xuansi/rigging"
    model = json.loads((source / "xuansi.model3.json").read_text("utf-8"))
    references = model["FileReferences"]
    references["Physics"] = ""
    references["Pose"] = ""
    names = ["xuansi.model3.json", references["Moc"], *references["Textures"]]
    if references.get("DisplayInfo"):
        names.append(references["DisplayInfo"])
    with zipfile.ZipFile(FIXTURES / "model.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            if name == "xuansi.model3.json":
                archive.writestr(name, json.dumps(model, indent=2))
            else:
                archive.write(source / name, name)
        archive.writestr("README.txt", "仅限本地验收，原模型版权与使用许可不变。\n")
        archive.writestr("legal/license.txt", "验收说明附件，不作为官方资源分发。\n")
    motion = {"Version": 3, "Meta": {"Duration": 0.5, "Fps": 30, "Loop": False,
        "AreBeziersRestricted": True, "CurveCount": 1, "TotalSegmentCount": 1,
        "TotalPointCount": 2, "UserDataCount": 0, "TotalUserDataSize": 0},
        "Curves": [{"Target": "Parameter", "Id": "ParamEyeLOpen", "Segments": [0, 1, 0, 0.5, 0]}]}
    expression = {"Type": "Live2D Expression", "Parameters": [
        {"Id": "ParamEyeLOpen", "Value": 0.3, "Blend": "Overwrite"}]}
    for filename, data in [("test.motion3.json", motion), ("test.exp3.json", expression)]:
        (FIXTURES / filename).write_text(json.dumps(data, indent=2), "utf-8")
    LOG.info("验收夹具已准备：图片、模型、动作和表情，原始素材未修改")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    prepare()
