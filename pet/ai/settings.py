"""版本化推理配置；仅保存凭据引用，验证证据绑定具体连接与工作模式。"""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field, fields
from urllib.parse import urlsplit

LOG = logging.getLogger(__name__)
CAPABILITIES = frozenset(('text', 'image', 'tools', 'stream', 'cancel', 'json'))


@dataclass(frozen=True)
class ModelProfile:
    provider: str = 'custom'
    region: str = 'custom'
    endpoint: str = ''
    model: str = ''
    mode: str = 'default'
    context_tokens: int = 16384
    credential_ref: str = ''
    capabilities: tuple[str, ...] = ('text',)
    verified_capabilities: tuple[str, ...] = ()
    verified_at: str = ''
    verification_fingerprint: str = ''

    def fingerprint(self):
        # Key 轮换使用新凭据引用，因此摘要改变而不需要读取或散列秘密。
        identity = {name: getattr(self, name) for name in (
            'provider', 'region', 'endpoint', 'model', 'mode', 'context_tokens', 'credential_ref',
            'capabilities',
        )}
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode('utf-8')).hexdigest()

    def is_verified(self, *capabilities: str):
        return bool(self.verified_at and self.verification_fingerprint == self.fingerprint()
                    and set(capabilities).issubset(self.verified_capabilities))

    def validate(self):
        for name in ('provider', 'region', 'endpoint', 'model', 'mode', 'credential_ref',
                     'verified_at', 'verification_fingerprint'):
            if not isinstance(getattr(self, name), str) or len(getattr(self, name)) > 2048:
                raise ValueError('在线模型配置字段无效。')
        if type(self.context_tokens) is not int or not 1024 <= self.context_tokens <= 2_000_000:
            raise ValueError('在线模型上下文预算需为 1024–2000000 token。')
        for values in (self.capabilities, self.verified_capabilities):
            if not isinstance(values, tuple) or not all(isinstance(value, str) and value in CAPABILITIES
                                                       for value in values):
                raise ValueError('在线模型能力声明无效。')
        if self.endpoint:
            try:
                url = urlsplit(self.endpoint)
                _ = url.port
            except ValueError:
                raise ValueError('API 地址无效。') from None
            loopback = url.hostname in ('localhost', '127.0.0.1', '::1')
            if (not url.hostname or url.scheme not in ('https', 'http')
                    or (url.scheme == 'http' and not loopback)
                    or url.username or url.password or url.query or url.fragment):
                raise ValueError('API 地址必须为 HTTPS；本机开发地址可使用 HTTP，地址不能包含秘密参数。')
        return self

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict):
            raise ValueError('在线模型配置应为对象。')
        allowed = {item.name for item in fields(cls)}
        values = {key: value for key, value in raw.items() if key in allowed}
        for name in ('capabilities', 'verified_capabilities'):
            if name in values:
                if not isinstance(values[name], (list, tuple)):
                    raise ValueError('在线模型能力应为列表。')
                values[name] = tuple(values[name])
        return cls(**values).validate()


@dataclass(frozen=True)
class AISettings:
    schema_version: int = 1
    policy: str = 'local_only'
    local_model: str = 'qwen3.5-9b'
    model_dir: str = ''
    backup_model_path: str = ''
    backup_projector_path: str = ''
    local_backend: str = 'auto'
    profile: ModelProfile = field(default_factory=ModelProfile)
    cloud_memory: bool = False
    cloud_observation: bool = False
    voice_components: tuple[str, ...] = ('asr', 'tts', 'realtime')

    def validate(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('推理配置版本暂不支持，请保留原文件并升级应用。')
        if self.policy not in ('local_only', 'local_first', 'online_first'):
            raise ValueError('推理策略无效。')
        if self.local_backend not in ('auto', 'cuda', 'cpu'):
            raise ValueError('本地计算后端无效。')
        if not isinstance(self.profile, ModelProfile):
            raise ValueError('在线模型档案无效。')
        self.profile.validate()
        if self.policy != 'local_only' and not (self.profile.endpoint and self.profile.model):
            raise ValueError('请先填写在线 API 地址与模型。')
        if any(type(value) is not bool for value in (self.cloud_memory, self.cloud_observation)):
            raise ValueError('在线资料发送授权应为布尔值。')
        for name in ('local_model', 'model_dir', 'backup_model_path', 'backup_projector_path'):
            if not isinstance(getattr(self, name), str) or len(getattr(self, name)) > 2048:
                raise ValueError('本地模型路径配置无效。')
        if not isinstance(self.voice_components, tuple) or not set(self.voice_components).issubset(
                ('asr', 'tts', 'realtime')):
            raise ValueError('语音组件选择无效。')
        return self

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict):
            raise ValueError('推理配置应为对象。')
        allowed = {item.name for item in fields(cls)}
        values = {key: value for key, value in raw.items() if key in allowed}
        if 'profile' in values:
            values['profile'] = ModelProfile.from_dict(values['profile'])
        if 'voice_components' in values:
            if not isinstance(values['voice_components'], (list, tuple)):
                raise ValueError('语音组件应为列表。')
            values['voice_components'] = tuple(values['voice_components'])
        return cls(**values).validate()

    def to_dict(self):
        return asdict(self)
