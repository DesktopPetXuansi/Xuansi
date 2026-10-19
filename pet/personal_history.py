"""已成功使用的本机形象；路径仅在本机保存，同步正文通过固定白名单生成。"""

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from .appearance_import import AppearanceCandidate, installed_candidate
from .history_storage import HistoryFile, history_path
from .model_history import ModelHistory
from .platform_auth import website_url

__all__ = ['AppearanceHistory', 'ModelHistory']
LOG = logging.getLogger(__name__)
KINDS = {'DEFAULT', 'MODEL', 'IMAGE', 'ANIMATION'}


class AppearanceHistory(HistoryFile):
    def __init__(self, path=None, *, limit=100):
        super().__init__(path if path is not None else history_path('appearance-history.json'), limit=limit)

    def empty(self):
        return {**super().empty(), 'sync': {'enabled': False, 'url': '', 'user': ''}}

    def validate(self, raw):
        super().validate(raw)
        state = raw['sync']
        if (not isinstance(state, dict) or type(state.get('enabled')) is not bool
                or any(not isinstance(state.get(key), str) for key in ('url', 'user'))):
            raise ValueError('历史同步配置损坏')
        if state['enabled'] and (not state['url'] or not state['user']):
            raise ValueError('历史同步账号缺失')
        for item in raw['entries']:
            UUID(item['id'])
            datetime.fromisoformat(item['occurredAt'])
            if (item['kind'] not in KINDS or not isinstance(item['name'], str)
                    or not 1 <= len(item['name']) <= 120 or not isinstance(item['imageId'], str)
                    or not isinstance(item['versionId'], str) or item['sync'] not in ('local', 'pending', 'synced')
                    or not isinstance(item.get('target'), dict)):
                raise ValueError('形象历史记录损坏')
            for key in ('resourceId', 'resourceVersionId'):
                if item[key] is not None:
                    UUID(item[key])
        return raw

    def record(self, candidate):
        with self.lock:
            raw = self.read()
            state = raw['sync']
            manifest = candidate.prepared[0] if candidate.prepared else {}
            remote = bool(manifest and manifest.get('source') != 'local')
            item = {
                'id': str(uuid4()), 'kind': candidate.kind, 'name': candidate.name[:120] or '桌宠形象',
                'imageId': candidate.image_id, 'versionId': candidate.version_id,
                'resourceId': manifest.get('resourceId') if remote else None,
                'resourceVersionId': manifest.get('resourceVersionId') if remote else None,
                'occurredAt': datetime.now(timezone.utc).isoformat(),
                'sync': 'pending' if state['enabled'] else 'local',
                'target': {'url': state['url'], 'user': state['user']} if state['enabled'] else {},
            }
            raw['entries'] = [item, *raw['entries']][:self.limit]
            self.write(raw)
            LOG.info('形象使用历史已保存 kind=%s', candidate.kind)
            return item

    def bind(self, url, user):
        if not isinstance(user, str) or not user:
            raise ValueError('官网未返回账号身份，请重新授权。')
        with self.lock:
            raw = self.read()
            raw['sync'] = {'enabled': True, 'url': website_url(url), 'user': user}
            self.write(raw)
            LOG.info('用户已开启形象历史同步，不补传此前记录')

    def disable(self):
        with self.lock:
            raw = self.read()
            raw['sync']['enabled'] = False
            self.write(raw)
            LOG.info('用户已关闭形象历史同步')

    def pending(self, url, user):
        raw = self.read()
        target = {'url': website_url(url), 'user': user}
        if not raw['sync']['enabled'] or any(raw['sync'][key] != value for key, value in target.items()):
            return []
        return [item for item in raw['entries'] if item['sync'] == 'pending' and item['target'] == target]

    def mark_synced(self, identifier, target):
        with self.lock:
            raw = self.read()
            for item in raw['entries']:
                if item['id'] == identifier and item['target'] == target:
                    item['sync'] = 'synced'
            self.write(raw)

    @staticmethod
    def payload(item):
        return {'kind': 'APPEARANCE', 'appearanceKind': item['kind'],
                'resourceId': item['resourceId'], 'resourceVersionId': item['resourceVersionId'],
                'name': item['name'], 'occurredAt': item['occurredAt'], 'deviceLabel': '玄司桌面端'}

    def candidate(self, identifier, *, image_directory=None, resource_root=None):
        item = next((item for item in self.read()['entries'] if item['id'] == identifier), None)
        if item is None:
            raise ValueError('记录已移除，请刷新历史。')
        if item['kind'] == 'MODEL' or item['versionId']:
            try:
                return installed_candidate(item['versionId'], image_directory=image_directory,
                                           resource_root=resource_root)
            except (ValueError, OSError, KeyError):
                raise ValueError('这个形象的本机文件已丢失或损坏，请重新导入或下载。') from None
        if item['kind'] in {'IMAGE', 'ANIMATION'}:
            from .appearance import image_path

            path = image_path(item['imageId']) if image_directory is None else image_path(item['imageId'], image_directory)
            if not path.is_file():
                raise ValueError('这个形象的本机文件已丢失，请重新导入。')
        return AppearanceCandidate(item['kind'], item['name'], item['imageId'])
