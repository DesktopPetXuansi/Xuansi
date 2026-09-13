"""用虚拟显示器验证完整范围、跨屏物理坐标和缩放后的鼠标位置。"""

from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

import pytest
from mss.exception import ScreenShotError
from PIL import Image, ImageDraw

from pet.config import Settings, load_settings, save_settings
from pet.desktop import capture_screen


@pytest.fixture
def capture(monkeypatch):
    requests = []

    class Grabber:
        monitors = [
            {"left": -1920, "top": 0, "width": 5760, "height": 2160},
            {"left": -1920, "top": 0, "width": 1920, "height": 1080},
            {"left": 0, "top": 0, "width": 3840, "height": 2160},
        ]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def grab(self, bounds):
            requests.append(bounds)
            width, height = bounds["width"], bounds["height"]
            picture = Image.new("RGB", (width, height), "white")
            draw = ImageDraw.Draw(picture)
            # 四角有独立颜色，裁掉任何一边都会让基准失败。
            for x, y, color in [
                (0, 0, "red"),
                (width - 100, 0, "green"),
                (0, height - 100, "blue"),
                (width - 100, height - 100, "black"),
            ]:
                draw.rectangle((x, y, x + 99, y + 99), fill=color)
            return SimpleNamespace(size=picture.size, rgb=picture.tobytes())

    monkeypatch.setattr("pet.desktop.mss.mss", Grabber)
    return requests, Grabber


def test_default_captures_entire_monitor_without_merging_other_displays(capture):
    requests, _ = capture
    picture = Image.open(BytesIO(capture_screen(1920, 1080)))
    assert requests == [{"left": 0, "top": 0, "width": 3840, "height": 2160}]
    assert picture.size == (1600, 900)
    assert picture.getpixel((5, 5))[0] > 230
    assert picture.getpixel((1594, 5))[1] > 100
    assert picture.getpixel((5, 894))[2] > 230
    assert max(picture.getpixel((1594, 894))) < 20
    # 鼠标缩放到 (800,450)，红圈不能留在原始大图坐标。
    red, green, blue = picture.getpixel((809, 450))
    assert red > green + 60 and red > blue + 60


def test_negative_monitor_coordinates_and_optional_nearby_mode(capture):
    requests, _ = capture
    assert Image.open(BytesIO(capture_screen(-1910, 20))).size == (1600, 900)
    assert requests[-1] == {"left": -1920, "top": 0, "width": 1920, "height": 1080}
    assert Image.open(BytesIO(capture_screen(-1910, 20, "nearby"))).size == (640, 448)
    assert requests[-1]["left"] == -1920 and requests[-1]["top"] == 0


def test_portrait_monitor_is_not_cropped_or_stretched(capture):
    _, grabber = capture
    grabber.monitors = [{}, {"left": 0, "top": -2560, "width": 1440, "height": 2560}]
    assert Image.open(BytesIO(capture_screen(500, -1000))).size == (900, 1600)


def test_disconnected_display_does_not_capture_a_different_screen(capture):
    requests, grabber = capture
    with pytest.raises(ScreenShotError):
        capture_screen(10000, 10000)
    grabber.monitors = [{}]
    with pytest.raises(ScreenShotError):
        capture_screen(0, 0)
    assert not requests


def test_scope_defaults_to_screen_and_persists(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    assert load_settings(path).capture_scope == "screen"
    save_settings(replace(Settings(), capture_scope="nearby"), path)
    assert load_settings(path).capture_scope == "nearby"
    with pytest.raises(ValueError):
        replace(Settings(), capture_scope="unknown").validate()
