"""官网授权与网络协议回归；测试令牌仅存内存。"""

import asyncio
import base64
import hashlib
import io
import json
import threading
import zipfile
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen
from uuid import uuid4

import httpx
import pytest

from pet.platform_api import PlatformClient
from pet.platform_auth import authorize


class MemoryStore:
    def __init__(self):
        self.tokens = {"access_token": "expired", "refresh_token": "refresh"}

    def read(self):
        return self.tokens

    def save(self, tokens):
        self.tokens = tokens

    def delete(self):
        self.tokens = None


def test_refresh_rotation_and_revoke(monkeypatch):
    store = MemoryStore()
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path == "/oauth/token":
            assert b"grant_type=refresh_token" in request.content
            return httpx.Response(200, json={"access_token": "new", "refresh_token": "rotated"})
        if request.url.path == "/oauth/revoke":
            assert b"token=rotated" in request.content
            return httpx.Response(200)
        if request.headers.get("Authorization") != "Bearer new":
            return httpx.Response(401)
        return httpx.Response(200, json={"data": [{"id": "resource"}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))
    async def run():
        client = PlatformClient("http://localhost:3000", store)
        assert await client.request("GET", "/me/library") == [{"id": "resource"}]
        assert store.tokens["refresh_token"] == "rotated"
        await client.logout()
        assert store.tokens is None
    asyncio.run(run())
    assert len(calls) == 4


def test_rejected_refresh_clears_only_platform_credentials(monkeypatch):
    store = MemoryStore()
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(401)), **kwargs))
    with pytest.raises(ValueError, match="授权已失效"):
        asyncio.run(PlatformClient("http://localhost:3000", store).request("GET", "/me/library"))
    assert store.tokens is None


@pytest.mark.parametrize("upload,scope", [(False, "resources:read"), (True, "resources:read resources:write")])
def test_authorization_real_loopback_and_pkce(monkeypatch, upload, scope):
    query = {}
    def browser(url):
        query.update(parse_qs(urlsplit(url).query))
        redirect = query["redirect_uri"][0]
        callback = redirect + "?" + urlencode({"state": query["state"][0], "code": "test-code"})
        with urlopen(callback, timeout=3) as response:
            assert response.status == 200
        return True
    monkeypatch.setattr("pet.platform_auth.webbrowser.open", browser)
    def handler(request):
        form = parse_qs(request.content.decode())
        verifier = form["code_verifier"][0]
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        assert expected == query["code_challenge"][0]
        assert query["code_challenge_method"] == ["S256"]
        assert query["scope"] == [scope]
        assert form["redirect_uri"] == query["redirect_uri"]
        return httpx.Response(200, json={"access_token": "test-access", "refresh_token": "test-refresh", "scope": scope})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))
    assert asyncio.run(authorize("http://localhost:3000", upload=upload))["access_token"] == "test-access"


def test_cancel_install_preserves_package_until_disk_work_finishes(tmp_path, monkeypatch):
    """安装取消必须等待不可取消的文件线程结束，随后才能清理暂存包。"""
    resource, version, model = str(uuid4()), str(uuid4()), str(uuid4())
    content = b'{"Type":"Live2D Expression","Parameters":[]}'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("test.exp3.json", content)
    package_bytes = stream.getvalue()
    manifest = {"schemaVersion": 1, "resourceId": resource, "resourceVersionId": version,
                "kind": "EXPRESSION", "version": "1.0.0", "minimumClientVersion": "0.5.6",
                "entrypoint": "test.exp3.json", "dependencies": [{"resourceId": str(uuid4()),
                    "resourceVersionId": model, "kind": "MODEL", "relation": "TARGET_MODEL"}],
                "files": [{"path": "test.exp3.json", "bytes": len(content),
                           "sha256": hashlib.sha256(content).hexdigest()}]}
    authorization = {"url": "http://localhost:3000/download", "bytes": len(package_bytes),
                     "sha256": hashlib.sha256(package_bytes).hexdigest()}
    entered, release = threading.Event(), threading.Event()
    packages = []
    def blocked_install(package, *_):
        packages.append(package)
        entered.set()
        assert release.wait(5)
        assert package.read_bytes() == package_bytes
    monkeypatch.setattr("pet.platform_api.install_package", blocked_install)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=package_bytes)), **kwargs))
    async def request(_method, path, _payload=None):
        return json.loads(json.dumps(manifest if path.endswith("/manifest") else authorization))
    async def run():
        client = PlatformClient("http://localhost:3000", MemoryStore())
        client.request = request
        task = asyncio.create_task(client.install(resource, version, tmp_path / "installed"))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and packages[0].is_file()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not packages[0].exists()
    try:
        asyncio.run(run())
    finally:
        release.set()
