"""用户明确指定的本地长期记忆；自动观察和原始会话不落盘。"""

import asyncio
import json
import logging
import re
import threading
from pathlib import Path

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


class MemoryStore:
    def __init__(self, path: Path = DATA / "memory.json"):
        self.path = path
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            return self._read()

    def _read(self):
        try:
            text = json.loads(self.path.read_text(encoding="utf-8"))["notes"]
            return text if isinstance(text, str) else ""
        except FileNotFoundError:
            return ""
        except (ValueError, KeyError, TypeError):
            LOG.warning("记忆文件损坏，保留文件并等待用户修正")
            return ""

    def context(self, query: str, limit=700):
        """按关键词与最近记录选择有限记忆，避免长期资料挤爆本地上下文。"""
        notes = self.read().splitlines()
        terms = {query[i : i + 2].lower() for i in range(len(query) - 1) if query[i : i + 2].isalnum()}
        ranked = sorted(
            enumerate(notes),
            key=lambda pair: (sum(term in pair[1].lower() for term in terms), pair[0]),
            reverse=True,
        )
        selected = []
        size = 0
        for _, note in ranked:
            if size >= limit:
                break
            selected.append(note[: limit - size])
            size += len(selected[-1]) + 1
        return "\n".join(selected)

    def save(self, text: str):
        with self.lock:
            self._save(text)

    def _save(self, text: str):
        if len(text) > 6000:
            raise ValueError("长期记忆最多 6000 字，请整理后保存。")
        if SECRET.search(text):
            raise ValueError("长期记忆不保存密码、验证码、密钥、证件或银行卡信息。")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"notes": text.strip()}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)
        LOG.info("本地记忆已更新 chars=%d", len(text))

    def remember_explicit(self, text: str):
        with self.lock:
            return self._remember_explicit(text)

    def _remember_explicit(self, text: str):
        match = re.match(r"^(?:请|你要|帮我)?(?:记住|记一下)[，,:：\s]*(.+)$", text.strip(), flags=re.S)
        if not match:
            return False
        note = match[1].strip()[:500]
        old = self.read()
        if note not in old.splitlines():
            self.save("\n".join(filter(None, (old, note))))
        return True
