"""设置加载诊断与受保护保存；恢复不写盘，覆盖前保留无效配置的原始字节。"""

import json
import logging
import os
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from uuid import uuid4

from .ai.settings import AISettings
from .config import Settings

LOG = logging.getLogger(__name__)
INVALID_VALUES = (ValueError, TypeError, AttributeError)


@dataclass(frozen=True)
class SettingsLoad:
    settings: Settings
    warning: str = ""


def _document(payload):
    raw = json.loads(payload.decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("配置必须是对象")
    return raw


def _parse(raw):
    values = {item.name: raw[item.name] for item in fields(Settings) if item.name in raw}
    if "ai" in values:
        values["ai"] = AISettings.from_dict(values["ai"])
    return Settings(**values).validate()


def _unsupported_version(raw):
    ai = raw.get("ai")
    if not isinstance(ai, dict):
        return False
    version = ai.get("schema_version", 1)
    return type(version) is not int or version != 1


def _recover(raw):
    settings = Settings()
    invalid = []
    # 按字段定义顺序恢复：先确定引擎，再验证受它约束的音色。
    # AI 配置作为整体校验，不能拼出未经用户授权的在线发送策略。
    for item in fields(Settings):
        if item.name not in raw:
            continue
        try:
            value = AISettings.from_dict(raw[item.name]) if item.name == "ai" else raw[item.name]
            settings = replace(settings, **{item.name: value}).validate()
        except INVALID_VALUES:
            invalid.append(item.name)
    return settings, invalid


def read_settings(path: Path):
    try:
        raw = _document(path.read_bytes())
    except FileNotFoundError:
        return SettingsLoad(Settings())
    except (ValueError, OSError) as exc:
        LOG.warning("配置无法读取，保留原文件并禁止覆盖 type=%s", type(exc).__name__)
        return SettingsLoad(Settings(), "原配置无法读取，暂用默认设置。原文件已保留；请修复或移走原文件后再保存。")
    try:
        return SettingsLoad(_parse(raw))
    except INVALID_VALUES:
        settings, invalid = _recover(raw)
        warning = "部分配置无效（" + "、".join(invalid) + "），已使用这些项的默认值，其余设置已保留。"
        if _unsupported_version(raw):
            warning += "推理配置版本不受支持，请升级应用或修复原文件后再保存。"
        else:
            warning += "原文件未改动；下次保存会先备份原文件。"
        LOG.warning("配置按字段恢复 fields=%s", ",".join(invalid))
        return SettingsLoad(settings, warning)


def _backup_if_needed(path):
    try:
        original = path.read_bytes()
    except FileNotFoundError:
        return
    try:
        raw = _document(original)
    except ValueError:
        LOG.warning("原配置无法解析，拒绝覆盖")
        raise ValueError("原配置无法解析，已禁止覆盖；请先修复或移走原文件，再保存设置。") from None
    if _unsupported_version(raw):
        LOG.warning("原配置版本不受支持，拒绝覆盖")
        raise ValueError("原配置版本不受支持，已禁止覆盖；请升级应用或修复原文件。")
    try:
        _parse(raw)
    except INVALID_VALUES:
        # 备份与临时文件均独占创建；备份失败就停止，绝不替换原文件。
        backup = path.with_name(path.name + "." + uuid4().hex + ".bak")
        with backup.open("xb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        LOG.warning("无效配置原件已备份 file=%s", backup.name)


def write_settings(settings: Settings, path: Path):
    settings.validate()
    _backup_if_needed(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(asdict(settings), stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    LOG.info("设置已保存")
