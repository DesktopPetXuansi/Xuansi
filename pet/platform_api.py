"""官网异步 API 与限量流式下载，鉴权仅发往官网自身。"""

import asyncio
import logging
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from .memory import durable_io
from .platform_auth import CLIENT_ID, CredentialStore, website_url
from .platform_resources import MAX_BYTES, RESOURCE_ROOT, install_package, validate_manifest

LOG = logging.getLogger(__name__)


class PlatformClient:
    def __init__(self, base_url, store=None):
        self.base_url = website_url(base_url)
        self.store = store or CredentialStore(self.base_url)
        self.pending_model_upload = None

    async def request(self, method, path, payload=None, *, headers=None, anonymous=False):
        # 公共发现完全绕开凭据读取与令牌刷新，失效登录不影响查看公共形象。
        tokens = None if anonymous else await asyncio.to_thread(self.store.read)
        async with httpx.AsyncClient(timeout=30) as client:
            async def send(current):
                request_headers = httpx.Headers(headers or {})
                if anonymous:
                    request_headers.pop("Authorization", None)
                if current:
                    request_headers["Authorization"] = f"Bearer {current['access_token']}"
                return await client.request(method, self.base_url + "/api/v1" + path,
                                            json=payload, headers=request_headers)
            response = await send(tokens)
            if response.status_code == 401 and tokens:
                tokens = await self.refresh_tokens(client, tokens)
                response = await send(tokens)
            response.raise_for_status()
            return response.json()["data"] if response.content else None

    async def refresh_tokens(self, client, tokens):
        """API 和流式上传共用令牌轮换，重试保留原来的完成幂等键。"""
        response = await client.post(self.base_url + "/oauth/token", data={
            "grant_type": "refresh_token", "client_id": CLIENT_ID,
            "refresh_token": tokens["refresh_token"]})
        if response.status_code != 200:
            await asyncio.to_thread(self.store.delete)
            raise ValueError("官网授权已失效，请重新登录")
        refreshed = response.json()
        if not refreshed.get("access_token") or not refreshed.get("refresh_token"):
            raise ValueError("官网未返回完整授权令牌")
        await asyncio.to_thread(self.store.save, refreshed)
        return refreshed

    async def upload_model(self, source, metadata=None, progress=None):
        """上传流程独立于下载，使用已明确授予的本人资源写权限。"""
        from .platform_upload import finalize_upload, upload_model

        if self.pending_model_upload:
            return await finalize_upload(self, progress)
        return await upload_model(self, source, metadata, progress)

    async def logout(self):
        tokens = await asyncio.to_thread(self.store.read)
        try:
            if tokens:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.post(self.base_url + "/oauth/revoke", data={
                        "token": tokens["refresh_token"], "client_id": CLIENT_ID})
                    response.raise_for_status()
        finally:
            await asyncio.to_thread(self.store.delete)
            LOG.info("官网本地授权凭据已清除")

    async def install(self, resource_id, version_id, root=RESOURCE_ROOT):
        prefix = f"/resources/{resource_id}/versions/{version_id}"
        manifest = validate_manifest(await self.request("GET", prefix + "/manifest"))
        if manifest["resourceId"] != resource_id or manifest["resourceVersionId"] != version_id:
            raise ValueError("服务器返回资源身份不符")
        authorization = await self.request("POST", prefix + "/download-authorizations", {})
        url = urljoin(self.base_url + "/", authorization["url"])
        parsed = urlsplit(url)
        website_url(f"{parsed.scheme}://{parsed.netloc}")
        if type(authorization["bytes"]) is not int or not 0 < authorization["bytes"] <= MAX_BYTES:
            raise ValueError("下载包超出大小限制")
        with tempfile.TemporaryDirectory(prefix="pet-platform-") as staging:
            package = Path(staging) / "download.zip"
            size = 0
            async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with package.open("xb") as output:
                        async for chunk in response.aiter_bytes(128 * 1024):
                            size += len(chunk)
                            if size > authorization["bytes"]:
                                raise ValueError("下载内容超过声明大小")
                            await durable_io(output.write, chunk)
            await durable_io(install_package, package, manifest, authorization, root)
        return manifest
