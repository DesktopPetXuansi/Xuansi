"""用户明确指定的本地长期记忆；自动观察和原始会话不落盘。"""

import asyncio
import json
import logging
import re
import threading
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .config import DATA

LOG = logging.getLogger(__name__)
SECRET = re.compile(
    r"密码|验证码|密钥|私钥|身份证|银行卡|api[_ -]?key|access[_ -]?token|sk-[A-Za-z0-9_-]{12,}|\b\d{15,19}\b",
    re.I,
)


async def durable_io(operation, *args):
    """取消时等本次短文件写入结束，防止已清空的数据被后台写回。"""
    pending = asyncio.create_task(asyncio.to_thread(operation, *args))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        await pending
        raise


@dataclass(frozen=True)
class MemoryEntry:
    id: str
    text: str
    revision: int
    source: str
    updated_at: str
    previous: tuple[str, ...] = ()


class MemoryStore:
    _locks = {}
    _locks_guard = threading.Lock()

    def __init__(self, path: Path = DATA / "memory.json"):
        self.path = path
        with self._locks_guard:
            self.lock = self._locks.setdefault(path.resolve(), threading.RLock())

    def read(self):
        return "\n".join(entry.text for entry in self.entries())

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return [], None
        if not isinstance(data, dict) or not isinstance(data.get("notes"), str):
            raise ValueError("记忆文件无法读取，已保留原文件。")
        if "entries" not in data:
            legacy = data["notes"]
            entries = [self._entry(text, "legacy") for text in legacy.strip().splitlines()]
            self._write(entries, legacy, validate=False)
            return entries, legacy
        try:
            entries = [MemoryEntry(**{**item, "previous": tuple(item["previous"])}) for item in data["entries"]]
            if any(not isinstance(item.text, str) or type(item.revision) is not int
                   or not all(isinstance(value, str) for value in item.previous) for item in entries):
                raise ValueError("invalid entry")
        except (KeyError, TypeError, ValueError):
            raise ValueError("记忆文件无法读取，已保留原文件。") from None
        return entries, data.get("legacy_notes")

    def entries(self):
        with self.lock:
            try:
                return tuple(self._load()[0])
            except (ValueError, KeyError, TypeError, AttributeError):
                LOG.warning("记忆文件损坏，保留文件并等待用户修正")
                return ()

    @staticmethod
    def _entry(text, source):
        return MemoryEntry(uuid4().hex, text, 1, source, datetime.now(UTC).isoformat())

    def context(self, query: str, limit=700):
        """保持同步字符串接口，仅提供原始候选；相关性由推理层的模型选择。"""
        return self.read()[:max(0, limit)]

    def save(self, text: str, expected=None):
        with self.lock:
            entries, legacy = self._load()
            if expected is not None and tuple(entries) != expected:
                raise ValueError("记忆已更新，请重新选择或编辑。")
            by_text = {}
            for entry in reversed(entries):
                by_text.setdefault(entry.text, []).append(entry)
            updated = []
            for line in text.strip().splitlines():
                matches = by_text.get(line)
                updated.append(matches.pop() if matches else self._entry(line, "manual"))
            self._write(updated, legacy if not any(by_text.values()) else None)

    def _write(self, entries, legacy=None, *, validate=True):
        text = "\n".join(entry.text for entry in entries)
        if validate and len(text) > 6000:
            raise ValueError("长期记忆最多 6000 字，请整理后保存。")
        if validate and SECRET.search(text):
            raise ValueError("长期记忆不保存密码、验证码、密钥、证件或银行卡信息。")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        data = {"notes": text, "entries": [asdict(entry) for entry in entries]}
        if legacy is not None:
            data["legacy_notes"] = legacy
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        LOG.info("本地记忆已更新 chars=%d", len(text))

    def change(self, action, identifier, revision, text="", source="manual"):
        with self.lock:
            entries, legacy = self._load()
            index = next((i for i, item in enumerate(entries) if item.id == identifier), None)
            if index is None or entries[index].revision != revision:
                raise ValueError("这条记忆已更改或删除，请重新选择。")
            old = entries[index]
            if action == "forget":
                # 旧格式备份也可能含这条记忆，永不从备份自动恢复。
                entries.pop(index)
                self._write(entries, validate=False)
                return None
            if action == "edit":
                text = text.strip()
                if not text or len(text.splitlines()) != 1:
                    raise ValueError("请输入一行有效的记忆。")
                if text == old.text:
                    return old
                previous = (*old.previous, old.text)
            elif action == "undo" and old.previous:
                text, previous = old.previous[-1], old.previous[:-1]
            else:
                raise ValueError("没有可撤销的更正。")
            updated = replace(old, text=text, revision=old.revision + 1, source=source,
                              updated_at=datetime.now(UTC).isoformat(), previous=previous)
            entries[index] = updated
            self._write(entries, legacy)
            return updated

    def remember(self, note: str, source: str = "", turn=None):
        """接收已由模型确认的明确事项；保存层不再按用户口令判断意图。"""
        # 同时检查源文，防止模型提取事项时删掉密码等敏感标签后绕过既有规则。
        if SECRET.search(source):
            raise ValueError("长期记忆不保存密码、验证码、密钥、证件或银行卡信息。")
        note = note.strip()
        if not note or len(note) > 500:
            raise ValueError("单条长期记忆需为 1–500 字，请整理后再保存。")
        with self.lock:
            entries, legacy = self._load()
            existing = {entry.text for entry in entries}
            additions = [self._entry(line, f"turn:{turn}" if turn is not None else "dialogue")
                         for line in dict.fromkeys(note.splitlines()) if line not in existing]
            if additions:
                self._write([*entries, *additions], legacy)
        return True
