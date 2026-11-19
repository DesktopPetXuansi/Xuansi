"""匿名公告同步与本机已读、提醒状态。"""

import json
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from PySide6.QtCore import QIODevice, QSaveFile

from .platform_auth import website_url

OFFICIAL_SOURCE = "https://xuansi.kukude.top"
RESPONSE_LIMIT = 1024 * 1024
PAGE_SIZE = 32
BLOCK_TYPES = {"paragraph", "heading", "strong", "bullet", "link"}


def https_link(text):
    if (not isinstance(text, str) or len(text.encode("utf-8")) > 1000
            or any(c.isspace() or c == "\\" or unicodedata.category(c) == "Cc" for c in text)):
        return False
    try:
        target = urlsplit(text)
        return (target.scheme == "https" and bool(target.hostname) and target.username is None
                and target.port != 0)
    except ValueError:
        return False


def _text(value, size):
    return (isinstance(value, str) and bool(value.strip()) and len(value.encode("utf-8")) <= size
            and all(unicodedata.category(char) != "Cc" for char in value))


def _change(value, after):
    if not isinstance(value, dict):
        raise ValueError("invalid announcement change")
    identifier = value.get("id")
    revision = value.get("revision")
    if not isinstance(identifier, str) or str(UUID(identifier)) != identifier:
        raise ValueError("invalid announcement id")
    if type(revision) is not int or not after < revision < 2**63:
        raise ValueError("invalid announcement revision")
    status = value.get("status")
    if status == "withdrawn":
        return {"id": identifier, "revision": revision, "status": status}
    if status != "published" or not _text(value.get("title"), 300) or value.get("level") not in ("normal", "important"):
        raise ValueError("invalid published announcement")
    stamp = value.get("publishedAt")
    if not isinstance(stamp, str) or datetime.fromisoformat(stamp).tzinfo is None:
        raise ValueError("invalid announcement timestamp")
    body = value.get("body")
    if not isinstance(body, list) or not 1 <= len(body) <= 24:
        raise ValueError("invalid announcement body")
    blocks = []
    for block in body:
        if not isinstance(block, dict) or block.get("kind") not in BLOCK_TYPES or not _text(block.get("text"), 1800):
            raise ValueError("invalid announcement block")
        kind, text = block["kind"], block["text"]
        target = block.get("url", "")
        if kind == "link" and not https_link(target):
            # 避免一个地址的解析差异阻止整页公告及后续撤回。仅向用户展示其文字。
            kind, target = "paragraph", ""
        if kind != "link" and target:
            raise ValueError("invalid announcement link")
        blocks.append({"kind": kind, "text": text, "url": target})
    return {"id": identifier, "revision": revision, "status": status, "title": value["title"],
            "level": value["level"], "publishedAt": stamp, "body": blocks}


@dataclass
class AnnouncementCache:
    revision: int = 0
    initialized: bool = False
    etag: str = ""
    synced_at: str = ""
    entries: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw["format"] != 1 or type(raw["revision"]) is not int or raw["revision"] < 0:
                return cls()
            entries = {}
            for item in raw["entries"]:
                entry = _change(item, 0)
                if entry["status"] != "published" or entry["revision"] > raw["revision"]:
                    return cls()
                entry["read"] = item.get("read") is True
                entry["reminded"] = item.get("reminded") is True
                entries[entry["id"]] = entry
            etag = raw.get("etag", "")
            synced_at = raw["syncedAt"]
            if not isinstance(etag, str) or not isinstance(synced_at, str):
                return cls()
            if synced_at and datetime.fromisoformat(synced_at).tzinfo is None:
                return cls()
            return cls(raw["revision"], raw["initialized"] is True, etag, synced_at, entries)
        except (OSError, TypeError, ValueError, KeyError, AttributeError):
            return cls()

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"format": 1, "revision": self.revision, "initialized": self.initialized,
                              "etag": self.etag, "syncedAt": self.synced_at, "entries": list(self.entries.values())},
                             ensure_ascii=False).encode("utf-8")
        output = QSaveFile(str(path))
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(output.errorString())
        if output.write(payload) != len(payload):
            output.cancelWriting()
            raise OSError(output.errorString())
        if not output.commit():
            raise OSError(output.errorString())

    def apply(self, delta):
        changes, revision, etag, reset = delta
        entries = {} if reset else self.entries.copy()
        for item in changes:
            key = item["id"]
            if item["status"] == "withdrawn":
                entries.pop(key, None)
                continue
            previous = self.entries.get(key, {})
            entries[key] = {**item, "read": previous.get("read", False),
                            "reminded": not self.initialized or reset or previous.get("reminded", False)}
        return AnnouncementCache(revision, True, etag, datetime.now(timezone.utc).isoformat(), entries)

    def mark(self, identifiers, field_name):
        for identifier in identifiers:
            if identifier in self.entries:
                self.entries[identifier][field_name] = True

    def pending(self):
        return [entry for entry in self.entries.values()
                if entry["level"] == "important" and not entry["read"] and not entry["reminded"]]


async def fetch_announcements(source, revision, etag, *, transport=None):
    url = website_url(source) + "/api/v1/client/announcements"
    changes, reset = [], False
    async with httpx.AsyncClient(timeout=12, follow_redirects=False, transport=transport) as client:
        while True:
            headers = {"If-None-Match": etag} if etag else {}
            async with client.stream("GET", url, params={"after": revision}, headers=headers) as response:
                if response.status_code == 304 and etag and not changes:
                    return changes, revision, etag, reset
                content = bytearray()
                if response.status_code != 409:
                    response.raise_for_status()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    content.extend(chunk)
                    if len(content) > RESPONSE_LIMIT:
                        raise ValueError("announcement feed too large")
                data = json.loads(content)
                if response.status_code == 409:
                    if not reset and revision and data.get("error", {}).get("code") == "ANNOUNCEMENT_CURSOR_RESET":
                        changes, revision, etag, reset = [], 0, "", True
                        continue
                    response.raise_for_status()
                data = data["data"]
                items, has_more = data["changes"], data["hasMore"]
                if (not isinstance(items, list) or len(items) > PAGE_SIZE or type(has_more) is not bool
                        or has_more and not items):
                    raise ValueError("invalid announcement page")
                for value in items:
                    change = _change(value, revision)
                    changes.append(change)
                    revision = change["revision"]
                if not has_more:
                    # 只保留空页的 ETag。非空页会推进游标，下一次请求不再是同一页。
                    return changes, revision, response.headers.get("ETag", "") if not items else "", reset
                etag = ""
