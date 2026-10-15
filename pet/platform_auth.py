"""官网授权与 Windows 凭据保管；令牌永不进入设置文件或日志。"""

import asyncio
import base64
import ctypes
import hashlib
import json
import logging
import secrets
import webbrowser
from ctypes import wintypes
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

LOG = logging.getLogger(__name__)
CLIENT_ID = "desktop-ai-pet"


def website_url(value):
    """仅回环开发地址允许 HTTP；禁止用户信息和非根路径。"""
    parsed = urlsplit(value)
    if (parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or not parsed.hostname
            or parsed.scheme not in ("https", "http")
            or parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1")):
        raise ValueError("官网地址必须使用 HTTPS；仅 localhost 回环地址允许 HTTP")
    return value.rstrip("/")


def pkce_pair():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class Credential(ctypes.Structure):
    """Win32 CREDENTIALW 布局；Windows 自行加密持久凭据。"""

    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


class CredentialStore:
    def __init__(self, base_url):
        self.target = f"desktop-ai-pet/platform/{website_url(base_url)}"
        self.api = ctypes.WinDLL("Advapi32", use_last_error=True)
        self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                     ctypes.POINTER(ctypes.POINTER(Credential))]
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.api.CredFree.argtypes = [ctypes.c_void_p]

    def save(self, tokens):
        blob = json.dumps(tokens).encode()
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = Credential(Type=1, TargetName=self.target, CredentialBlobSize=len(blob),
                                CredentialBlob=buffer, Persist=2, UserName=CLIENT_ID)
        if not self.api.CredWriteW(ctypes.byref(credential), 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def read(self):
        pointer = ctypes.POINTER(Credential)()
        if not self.api.CredReadW(self.target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return json.loads(ctypes.string_at(pointer.contents.CredentialBlob,
                                              pointer.contents.CredentialBlobSize))
        finally:
            self.api.CredFree(pointer)

    def delete(self):
        if not self.api.CredDeleteW(self.target, 1, 0) and ctypes.get_last_error() != 1168:
            raise ctypes.WinError(ctypes.get_last_error())


def callback_code(target, expected_state):
    parsed = urlsplit(target)
    values = parse_qs(parsed.query)
    state = values.get("state", [])
    code = values.get("code", [])
    if (parsed.path != "/oauth/callback" or len(state) != 1
            or not secrets.compare_digest(state[0], expected_state) or len(code) != 1):
        raise ValueError("授权回调校验失败")
    return code[0]


async def authorize(base_url, *, upload=False):
    """随机回环端口只处理本次 state；五分钟内完成系统浏览器授权。"""
    base_url = website_url(base_url)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(32)
    result = asyncio.get_running_loop().create_future()

    async def callback(reader, writer):
        status = "400 Bad Request"
        try:
            line = await asyncio.wait_for(reader.readline(), 5)
            method, target, _ = line.decode("ascii").split()
            if method != "GET":
                raise ValueError("回调方法无效")
            code = callback_code(target, state)
            if not result.done():
                result.set_result(code)
            status = "200 OK"
        except (ValueError, UnicodeError, asyncio.TimeoutError):
            LOG.warning("已拒绝无效官网授权回调")
        finally:
            body = "授权处理完成，请返回桌宠。".encode()
            writer.write(f"HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\n"
                         f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(callback, "127.0.0.1", 0, limit=8192)
    redirect = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/oauth/callback"
    scopes = "resources:read resources:write" if upload else "resources:read"
    query = urlencode({"response_type": "code", "client_id": CLIENT_ID, "redirect_uri": redirect,
                       "scope": scopes, "state": state, "code_challenge": challenge,
                       "code_challenge_method": "S256"})
    try:
        await asyncio.to_thread(webbrowser.open, f"{base_url}/oauth/authorize?{query}")
        code = await asyncio.wait_for(result, 300)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{base_url}/oauth/token", data={
                "grant_type": "authorization_code", "client_id": CLIENT_ID, "code": code,
                "redirect_uri": redirect, "code_verifier": verifier})
            response.raise_for_status()
            tokens = response.json()
            if not tokens.get("access_token") or not tokens.get("refresh_token"):
                raise ValueError("官网未返回完整授权令牌")
            return tokens
    finally:
        server.close()
        await server.wait_closed()
