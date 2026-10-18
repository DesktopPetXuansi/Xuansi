"""独立的模型 API Windows 凭据命名空间；普通设置仅保存随机引用。"""

import ctypes
import hashlib
import logging
import re
import uuid
from ctypes import wintypes
from urllib.parse import urlsplit

LOG = logging.getLogger(__name__)
PREFIX = 'desktop-ai-pet/model-api/'
REFERENCE = re.compile(r'[0-9a-f]{24}/[0-9a-f]{32}\Z')


def new_ref(endpoint):
    """端点摘要隔离服务，随机版本隔离未提交草稿与当前已保存 Key。"""
    parsed = urlsplit(endpoint)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('API 端点无效。')
    digest = hashlib.sha256(endpoint.rstrip('/').encode()).hexdigest()[:24]
    return digest + '/' + uuid.uuid4().hex


def ref_matches_endpoint(reference, endpoint):
    """端点变更不能沿用旧服务商 Key；仅显式传入的新草稿 Key 可另行验证。"""
    return bool(isinstance(reference, str) and REFERENCE.fullmatch(reference)
                and reference.split('/')[0] == hashlib.sha256(
                    endpoint.rstrip('/').encode()).hexdigest()[:24])


class _Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
                ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


class _WindowsVault:
    def __init__(self):
        self.api = ctypes.WinDLL('Advapi32', use_last_error=True)
        self.api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                     ctypes.POINTER(ctypes.POINTER(_Credential))]
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.api.CredFree.argtypes = [ctypes.c_void_p]

    def write(self, target, key):
        data = key.encode('utf-16-le')
        if len(data) > 2560:
            raise ValueError('API Key 超过 Windows 凭据容量。')
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        credential = _Credential(Type=1, TargetName=target, CredentialBlobSize=len(data),
                                 CredentialBlob=buffer, Persist=2, UserName='desktop-ai-pet-model-api')
        if not self.api.CredWriteW(ctypes.byref(credential), 0):
            raise OSError('Windows 凭据保存失败。')

    def read(self, target):
        pointer = ctypes.POINTER(_Credential)()
        if not self.api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise OSError('Windows 凭据读取失败。')
        try:
            return ctypes.string_at(pointer.contents.CredentialBlob,
                                    pointer.contents.CredentialBlobSize).decode('utf-16-le')
        finally:
            self.api.CredFree(pointer)

    def delete(self, target):
        if not self.api.CredDeleteW(target, 1, 0) and ctypes.get_last_error() != 1168:
            raise OSError('Windows 凭据删除失败。')


class CredentialStore:
    def __init__(self, *, vault=None):
        self._vault = vault

    def target(self, reference):
        if not isinstance(reference, str) or not REFERENCE.fullmatch(reference):
            raise ValueError('模型 API 凭据引用无效。')
        return PREFIX + reference

    @property
    def vault(self):
        if self._vault is None:
            self._vault = _WindowsVault()
        return self._vault

    def read(self, reference):
        if not reference:
            return None
        return self.vault.read(self.target(reference))

    def write(self, reference, key):
        target = self.target(reference)
        if not isinstance(key, str) or not key.strip() or '\r' in key or '\n' in key:
            raise ValueError('API Key 为空或格式无效。')
        self.vault.write(target, key)
        LOG.info('模型 API 凭据已保存')

    def delete(self, reference):
        if reference:
            self.vault.delete(self.target(reference))
            LOG.info('模型 API 凭据已删除')
