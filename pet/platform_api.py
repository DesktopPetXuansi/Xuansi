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

    async def request(self, method, path, payload=None):
        tokens = await asyncio.to_thread(self.store.read)
        async with httpx.AsyncClient(timeout=30) as client:
            async def send(current):
                headers = {"Authorization": f"Bearer {current['access_token']}"} if current else {}
                return await client.request(method, self.base_url + "/api/v1" + path,
                                            json=payload, headers=headers)
            response = await send(tokens)
            if response.status_code == 401 and tokens:
                refreshed = await client.post(self.base_url + "/oauth/token", data={
                    "grant_type": "refresh_token", "client_id": CLIENT_ID,
                    "refresh_token": tokens["refresh_token"]})
                if refreshed.status_code != 200:
                    await asyncio.to_thread(self.store.delete)
                    raise ValueError("官网授权已失效，请重新登录")
                tokens = refreshed.json()
                await asyncio.to_thread(self.store.save, tokens)
                response = await send(tokens)
            response.raise_for_status()
            return response.json()["data"] if response.content else None

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
