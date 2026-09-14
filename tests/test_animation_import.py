"""透明动图用人工像素基准验证帧序、处置、时长，避免只验证首帧。"""

import io
import struct

import pytest
from PIL import Image, ImageDraw

from pet.appearance import image_path, import_image


def webp_fixture(frames, durations):
    # 人工 RIFF 基准：使用可靠的静态无损 WebP 块，绕开本机动画编码器的 alpha 缺陷。
    def chunk(kind, data):
        return kind + struct.pack("<I", len(data)) + data + b"\0" * (len(data) % 2)

    width, height = frames[0].size
    canvas = (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    body = chunk(b"VP8X", b"\x12\0\0\0" + canvas) + chunk(b"ANIM", b"\0" * 6)
    for frame, duration in zip(frames, durations, strict=True):
        encoded = io.BytesIO()
        frame.save(encoded, format="WEBP", lossless=True)
        header = b"\0" * 6 + canvas + duration.to_bytes(3, "little") + b"\x02"
        body += chunk(b"ANMF", header + encoded.getvalue()[12:])
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body


@pytest.mark.parametrize("format", ["GIF", "WEBP", "PNG"])
def test_animated_import_preserves_transparency_frames_and_timing(tmp_path, format):
    frames = []
    for x, color in [(10, "red"), (40, "blue"), (70, "green")]:
        frame = Image.new("RGBA", (100, 100))
        ImageDraw.Draw(frame).rectangle((x, 30, x + 10, 60), fill=color)
        frames.append(frame)
    source = tmp_path / "animation"
    options = {"disposal": 2} if format == "GIF" else {}
    if format == "WEBP":
        source.write_bytes(webp_fixture(frames, [60, 120, 200]))
    else:
        frames[0].save(
            source,
            format=format,
            save_all=True,
            append_images=frames[1:],
            duration=[60, 120, 200],
            loop=0,
            **options,
        )
    asset = import_image(source, tmp_path / "assets")
    assert asset.identifier.endswith(".apng") and asset.frames == 3 and asset.transparent
    with Image.open(image_path(asset.identifier, tmp_path / "assets")) as result:
        assert result.n_frames == 3
        for index, (x, color) in enumerate([(10, (255, 0, 0)), (40, (0, 0, 255)), (70, (0, 128, 0))]):
            result.seek(index)
            frame = result.convert("RGBA")
            assert frame.getpixel((x + 5, 45)) == (*color, 255)
            assert frame.getpixel((1, 1))[3] == 0
            if index:
                assert frame.getpixel((15, 45))[3] == 0  # 前帧位置不留下拖影。
            assert result.info["duration"] == [60, 120, 200][index]


def test_apng_poster_is_not_an_animation_frame(tmp_path):
    path = tmp_path / "poster.png"
    Image.new("RGBA", (20, 20), "black").save(
        path,
        save_all=True,
        default_image=True,
        append_images=[Image.new("RGBA", (20, 20), "red"), Image.new("RGBA", (20, 20), "blue")],
        duration=[90, 160],
    )
    asset = import_image(path, tmp_path / "assets")
    with Image.open(image_path(asset.identifier, tmp_path / "assets")) as result:
        assert result.n_frames == 2
        assert result.convert("RGBA").getpixel((10, 10)) == (255, 0, 0, 255)


def test_excess_frames_are_rejected(tmp_path):
    source = tmp_path / "many.png"
    frames = [Image.new("RGBA", (10, 10), (x, 0, 0, 255)) for x in range(121)]
    frames[0].save(source, save_all=True, append_images=frames[1:], duration=50)
    with pytest.raises(ValueError, match="120"):
        import_image(source, tmp_path / "assets")
    assert not (tmp_path / "assets").exists()
