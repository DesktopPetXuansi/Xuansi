"""本机已保存模型配置历史；仅保留凭据引用，回选一律清除旧验证证据。"""

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

from .ai.credentials import CredentialStore, ref_matches_endpoint
from .ai.settings import AISettings
from .history_storage import HistoryFile, history_path

LOG = logging.getLogger(__name__)


class ModelHistory(HistoryFile):
    def __init__(self, path=None, *, limit=20, credentials=None):
        super().__init__(path if path is not None else history_path('model-history.json'), limit=limit)
        self.credentials = credentials or CredentialStore()

    def validate(self, raw):
        super().validate(raw)
        for item in raw['entries']:
            UUID(item['id'])
            datetime.fromisoformat(item['occurredAt'])
            AISettings.from_dict(item['ai'])
            if any(not isinstance(item[key], str) for key in ('modelPath', 'projectorPath', 'name', 'occurredAt')):
                raise ValueError('模型历史配置损坏')
        return raw

    def record(self, settings, model_path, projector_path):
        settings.validate()
        with self.lock:
            raw = self.read()
            # JSON 往返统一 tuple/list，重复保存同一配置不会产生多条历史。
            snapshot = json.loads(json.dumps(settings.to_dict()))
            identity = (snapshot, model_path, projector_path)
            previous = raw['entries']
            kept = [item for item in previous if (item['ai'], item['modelPath'], item['projectorPath']) != identity]
            raw['entries'] = [{
                'id': str(uuid4()), 'name': (settings.profile.model if settings.policy != 'local_only'
                                           else settings.local_model)[:120],
                'occurredAt': datetime.now(timezone.utc).isoformat(), 'ai': snapshot,
                'modelPath': model_path, 'projectorPath': projector_path,
            }, *kept][:self.limit]
            self.write(raw)
            LOG.info('已保存模型配置历史，未保存密钥正文')

    def configuration(self, identifier):
        item = next((item for item in self.read()['entries'] if item['id'] == identifier), None)
        if item is None:
            raise ValueError('记录已移除，请刷新历史。')
        settings = AISettings.from_dict(item['ai'])
        profile = replace(settings.profile, verified_capabilities=(), verified_at='', verification_fingerprint='')
        missing = False
        if profile.credential_ref:
            # 仅后台检查是否仍有系统凭据；密钥不返回 UI，不写历史文件。
            try:
                missing = (not ref_matches_endpoint(profile.credential_ref, profile.endpoint)
                           or not self.credentials.read(profile.credential_ref))
            except (OSError, ValueError):
                missing = True
            if missing:
                profile = replace(profile, credential_ref='')
        return replace(settings, profile=profile), item['modelPath'], item['projectorPath'], missing
