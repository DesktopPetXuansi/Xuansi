"""有限本机历史的串行读改写；损坏文件原样保留，提交使用原子替换。"""

import json
import logging
import os
import threading
from pathlib import Path
from uuid import uuid4

LOG = logging.getLogger(__name__)
_LOCKS = {}
_LOCK_GUARD = threading.Lock()


class HistoryFile:
    def __init__(self, path, *, limit=100):
        self.path, self.limit = Path(path), limit
        with _LOCK_GUARD:
            self.lock = _LOCKS.setdefault(str(self.path.absolute()), threading.RLock())

    def empty(self):
        return {'schema': 1, 'entries': []}

    def validate(self, raw):
        if (not isinstance(raw, dict) or raw.get('schema') != 1
                or not isinstance(raw.get('entries'), list) or len(raw['entries']) > self.limit):
            raise ValueError('历史文件损坏，已保留原文件，请备份并修复后重试。')
        return raw

    def read(self):
        with self.lock:
            try:
                if self.path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError('历史文件过大')
                return self.validate(json.loads(self.path.read_text(encoding='utf-8')))
            except FileNotFoundError:
                return self.empty()
            except (ValueError, KeyError, TypeError):
                LOG.warning('本机历史文件损坏，保留原件')
                raise ValueError('历史文件损坏，已保留原文件，请备份并修复后重试。') from None

    def write(self, raw):
        self.validate(raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.' + uuid4().hex + '.tmp')
        try:
            with temporary.open('x', encoding='utf-8') as stream:
                json.dump(raw, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def remove(self, identifier=None):
        if identifier is not None and (not isinstance(identifier, str) or not identifier.strip()):
            LOG.warning('拒绝无效的历史记录标识 type=%s', type(identifier).__name__)
            raise ValueError('历史记录标识必须为非空字符串。')
        with self.lock:
            raw = self.read()
            # 只有显式的 None 表示清空，其他合法标识只匹配一条记录。
            raw['entries'] = ([] if identifier is None
                              else [item for item in raw['entries'] if item['id'] != identifier])
            self.write(raw)
            LOG.info('本机历史已移除 clear=%s', identifier is None)


def history_path(filename):
    # 调用时解析 DATA，隔离测试可替换目录，不冻结用户路径为默认实参。
    from .config import DATA

    return DATA / filename
