"""本地设置；只保存用户明确配置，不保存对话、音频或屏幕。"""

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODELS = Path("D:/AI/Models/desktop-pet")
LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    name: str = "糯米"
    persona: str = "你是一只温柔、机灵的小猫，陪我工作和学习。自然地说中文，关心但不过度打扰。"
    system_prompt: str = "回复简短自然，通常一到两句话。看不清或无法确认的事情要直说，不要编造。"
    interval: int = 20
    pet_size: int = 96
    observe: bool = True
    speak_replies: bool = True
    speak_observations: bool = False
    tts_engine: str = "fast"
    follow_mouse: bool = False
    speaker: int = 0
    speed: float = 1.08
    input_device: int = -1
    model_path: str = str(MODELS / "Qwen3.5-4B-Q4_K_M.gguf")
    projector_path: str = str(MODELS / "mmproj-F16.gguf")
    gpu_layers: int = 99

    def validate(self):
        defaults = Settings()
        for field in fields(self):
            value, original = getattr(self, field.name), getattr(defaults, field.name)
            if type(value) is not type(original):
                raise ValueError(f"设置类型错误：{field.name}")
        if not 10 <= self.interval <= 300 or self.pet_size not in (64, 96, 128):
            raise ValueError("观察间隔为 10–300 秒，尺寸为 64、96 或 128")
        limit = 0 if self.tts_engine == "fast" else 102
        if (
            self.tts_engine not in ("fast", "natural")
            or not 0.7 <= self.speed <= 1.5
            or not 0 <= self.speaker <= limit
        ):
            raise ValueError("语速或音色超出范围")
        if not 0 <= self.gpu_layers <= 99 or self.input_device < -1:
            raise ValueError("设备或模型参数无效")
        if not self.name.strip() or len(self.name) > 40:
            raise ValueError("名字需为 1–40 字")
        if len(self.persona) > 4000 or len(self.system_prompt) > 8000:
            raise ValueError("人设最多 4000 字，系统提示词最多 8000 字")
        return self


def load_settings(path: Path = DATA / "settings.json"):
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        allowed = {field.name for field in fields(Settings)}
        return Settings(**{key: value for key, value in raw.items() if key in allowed}).validate()
    except FileNotFoundError:
        return Settings()
    except (ValueError, TypeError, AttributeError, OSError):
        LOG.warning("设置无法读取，使用默认值并保留原文件")
        return Settings()


def save_settings(settings: Settings, path: Path = DATA / "settings.json"):
    settings.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    LOG.info("设置已保存")
