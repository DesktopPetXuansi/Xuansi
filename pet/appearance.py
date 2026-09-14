"""导入用户选择的本机图片，生成有界、去元数据的 PNG/APNG 持久副本。"""

import hashlib
import io
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from .animation_import import encode_animation
from .config import DATA, ROOT

LOG = logging.getLogger(__name__)
DIRECTORY = DATA / "appearances"
DEFAULT_IMAGE = ROOT / "assets/xuansi/front.png"
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 16_000_000


@dataclass(frozen=True)
class ImportedImage:
    identifier: str
    width: int
    height: int
    transparent: bool
    frames: int = 1


def image_path(identifier, directory=DIRECTORY):
    if not identifier:
        return DEFAULT_IMAGE
    if not re.fullmatch(r"[0-9a-f]{64}\.(png|apng)", identifier):
        raise ValueError("形象记录无效，请重新选择图片")
    return directory / identifier


def import_image(source, directory=DIRECTORY):
    temporary = None
    try:
        if str(source).startswith(("\\\\", "//")):
            raise ValueError("请选择保存在本机磁盘的图片")
        # 限制实际读取量；不相信扩展名，也不把原图路径写入日志。
        with Path(source).open("rb") as stream:
            payload = stream.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise ValueError("图片超过 20 MB，请先缩小图片")
        with Image.open(io.BytesIO(payload), formats=("PNG", "WEBP", "JPEG", "BMP", "GIF")) as original:
            if original.width * original.height > MAX_PIXELS:
                raise ValueError("图片超过 1600 万像素，请先缩小图片")
            if getattr(original, "n_frames", 1) > 1:
                payload, size, transparent, count = encode_animation(original)
                extension = ".apng"
            else:
                result = ImageOps.exif_transpose(original).convert("RGBA")
                alpha = result.getchannel("A")
                if alpha.getextrema()[1] < 128:
                    raise ValueError("图片完全透明或过淡，无法作为可点击的桌宠")
                result = result.crop(alpha.getbbox())
                result.thumbnail((1536, 1536), Image.Resampling.LANCZOS)
                transparent = result.getchannel("A").getextrema()[0] < 255
                result.info.clear()
                encoded = io.BytesIO()
                result.save(encoded, format="PNG")
                payload, size, count, extension = encoded.getvalue(), result.size, 1, ".png"
        identifier = hashlib.sha256(payload).hexdigest() + extension
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f".{uuid.uuid4().hex}.tmp"
        temporary.write_bytes(payload)
        temporary.replace(image_path(identifier, directory))
        LOG.info("形象图片已导入 size=%sx%s transparent=%s frames=%s", *size, transparent, count)
        return ImportedImage(identifier, *size, transparent, count)
    except ValueError:
        raise
    except (OSError, Image.DecompressionBombError) as exc:
        LOG.warning("形象导入失败 type=%s", type(exc).__name__)
        raise ValueError("图片无法读取或保存，请检查格式、文件权限和磁盘空间") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
