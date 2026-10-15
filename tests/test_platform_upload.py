"""客户端直接上传的真实字节流、权限、取消及存储凭据边界回归。"""

import asyncio
import io
import json
import zipfile
from uuid import uuid4

import httpx
import pytest

from pet.platform_api import PlatformClient


class UploadStore:
    def __init__(self, scope="resources:read resources:write"):
        self.tokens = {"access_token": "test-access", "refresh_token": "test-refresh", "scope": scope}

    def read(self):
        return self.tokens

    def save(self, tokens):
        self.tokens = tokens

    def delete(self):
        self.tokens = None


def upload_source(root):
    root.mkdir()
    (root / "pet.moc3").write_bytes(b"MOC3\x01\x00\x00\x00example")
    (root / "texture.png").write_bytes(b"texture-content")
    entry = root / "pet.model3.json"
    entry.write_text(json.dumps({"Version": 3, "FileReferences": {
        "Moc": "pet.moc3", "Textures": ["texture.png"],
    }}), encoding="utf-8")
    return entry


@pytest.mark.parametrize("external", [False, True])
def test_upload_stream_validates_and_joins_library(tmp_path, monkeypatch, external):
    entry = upload_source(tmp_path / "model")
    resource_id, version_id, upload_id = str(uuid4()), str(uuid4()), str(uuid4())
    upload_path = f"/api/v1/uploads/{upload_id}"
    content_url = "https://storage.example.invalid/model?signature=test" if external else upload_path + "/content"
    states = ["VALIDATING", "READY"]
    completed, published, joined, progress = [], [], [], []
    original = httpx.AsyncClient

    async def handler(request):
        path = request.url.path
        if request.method == "PUT" and (path.endswith("/content") or request.url.host == "storage.example.invalid"):
            if external:
                assert "Authorization" not in request.headers and "Cookie" not in request.headers
            else:
                assert request.headers["Authorization"] == "Bearer test-access"
            body = await request.aread()
            assert int(request.headers["Content-Length"]) == len(body)
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                assert set(archive.namelist()) == {"pet.model3.json", "pet.moc3", "texture.png"}
            return httpx.Response(204)
        assert request.headers["Authorization"] == "Bearer test-access"
        assert "Cookie" not in request.headers and "X-CSRF-Token" not in request.headers
        body = json.loads(request.content) if request.content else None
        if path == "/api/v1/me":
            return httpx.Response(200, json={"data": {"displayName": "本机作者", "emailVerified": True}})
        if path == "/api/v1/resources":
            assert body["kind"] == "MODEL" and body["author"] == "本机作者" and body["name"] == "pet"
            return httpx.Response(201, json={"data": {"id": resource_id}})
        if path.endswith("/versions"):
            assert body["entrypoint"] == "pet.model3.json" and body["version"] == "1.0.0"
            return httpx.Response(201, json={"data": {
                "version": {"id": version_id}, "upload": {
                    "id": upload_id, "method": "PUT", "url": content_url,
                    "headers": {"Content-Type": "application/octet-stream"},
                },
            }})
        if path.endswith("/completion"):
            completed.append(request.headers["Idempotency-Key"])
            return httpx.Response(200, json={"data": {"status": "VALIDATING"}})
        if path == upload_path:
            return httpx.Response(200, json={"data": {"status": states.pop(0)}})
        if request.method == "PATCH":
            published.append(body)
            return httpx.Response(200, json={"data": {"id": resource_id}})
        if path.endswith("/library/" + resource_id):
            joined.append(body)
            return httpx.Response(204)
        raise AssertionError(f"不期望的测试接口：{path}")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))
    result = asyncio.run(PlatformClient("http://localhost:3000", UploadStore()).upload_model(
        entry, progress=lambda phase, percent: progress.append((phase, percent))))
    assert result["resourceId"] == resource_id and result["resourceVersionId"] == version_id
    assert len(completed) == 1 and len(completed[0]) >= 8
    assert published == [{"currentVersionId": version_id}]
    assert joined == [{"pinnedVersionId": version_id}]
    assert progress[-1][1] == 100


def test_read_only_upload_stops_before_network_and_packaging(tmp_path, monkeypatch):
    entry = upload_source(tmp_path / "model")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: pytest.fail("只读上传发起了网络请求"))
    with pytest.raises(ValueError, match="上传权限"):
        asyncio.run(PlatformClient("http://localhost:3000", UploadStore("resources:read")).upload_model(entry))


def test_upload_failure_cancels_reserved_upload(tmp_path, monkeypatch):
    entry = upload_source(tmp_path / "model")
    resource_id, version_id, upload_id = str(uuid4()), str(uuid4()), str(uuid4())
    cancelled = []
    original = httpx.AsyncClient

    async def handler(request):
        path = request.url.path
        if request.method == "DELETE":
            cancelled.append(path)
            return httpx.Response(204)
        if path == "/api/v1/me":
            return httpx.Response(200, json={"data": {"displayName": "作者", "emailVerified": True}})
        if path == "/api/v1/resources":
            return httpx.Response(201, json={"data": {"id": resource_id}})
        if path.endswith("/versions"):
            return httpx.Response(201, json={"data": {"version": {"id": version_id}, "upload": {
                "id": upload_id, "method": "PUT", "url": f"/api/v1/uploads/{upload_id}/content", "headers": {},
            }}})
        return httpx.Response(503)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(PlatformClient("http://localhost:3000", UploadStore()).upload_model(entry))
    assert cancelled == [f"/api/v1/uploads/{upload_id}"]


def test_library_failure_retries_same_ready_resource_without_uploading_again(tmp_path, monkeypatch):
    entry = upload_source(tmp_path / "model")
    resource_id, version_id, upload_id = str(uuid4()), str(uuid4()), str(uuid4())
    creates, joins = [], []
    original = httpx.AsyncClient

    async def handler(request):
        path = request.url.path
        if path == "/api/v1/me":
            return httpx.Response(200, json={"data": {"displayName": "作者", "emailVerified": True}})
        if path == "/api/v1/resources":
            creates.append(True)
            return httpx.Response(201, json={"data": {"id": resource_id}})
        if path.endswith("/versions"):
            return httpx.Response(201, json={"data": {"version": {"id": version_id}, "upload": {
                "id": upload_id, "method": "PUT", "url": f"/api/v1/uploads/{upload_id}/content", "headers": {},
            }}})
        if path.endswith("/content"):
            await request.aread()
            return httpx.Response(204)
        if path.endswith("/completion"):
            return httpx.Response(200, json={"data": {"status": "READY"}})
        if path == f"/api/v1/uploads/{upload_id}":
            return httpx.Response(200, json={"data": {"status": "READY"}})
        if request.method == "PATCH":
            assert json.loads(request.content) == {"currentVersionId": version_id}
            return httpx.Response(200, json={"data": {"id": resource_id}})
        if path.endswith("/library/" + resource_id):
            joins.append(True)
            return httpx.Response(503) if len(joins) == 1 else httpx.Response(204)
        raise AssertionError(f"非预期测试接口：{path}")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))
    client = PlatformClient("http://localhost:3000", UploadStore())
    with pytest.raises(ValueError, match="加入资源库"):
        asyncio.run(client.upload_model(entry))
    # 已校验模型只需恢复完成步骤，本地源文件是否存在不应触发重新打包。
    entry.unlink()
    result = asyncio.run(client.upload_model(entry))
    assert result["resourceId"] == resource_id and result["resourceVersionId"] == version_id
    assert len(creates) == 1 and len(joins) == 2
    assert client.pending_model_upload is None
