"""限量流式上传；官网凭据只发送给官网自己的上传接口。"""

import asyncio
from urllib.parse import urljoin, urlsplit

import httpx

from .memory import durable_io
from .platform_resources import identifier


def upload_target(client, upload):
    upload_id = identifier(upload["id"])
    if upload.get("method") != "PUT":
        raise ValueError("官网未提供支持的 PUT 上传地址")
    target = urljoin(client.base_url + "/", upload["url"])
    parsed, base = urlsplit(target), urlsplit(client.base_url)
    same_origin = (parsed.scheme, parsed.hostname, parsed.port) == (base.scheme, base.hostname, base.port)
    if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:
        raise ValueError("上传地址不符合安全要求")
    if same_origin:
        if parsed.path != f"/api/v1/uploads/{upload_id}/content" or parsed.query:
            raise ValueError("官网上传地址与上传身份不符")
    elif parsed.scheme != "https":
        raise ValueError("外部存储上传地址必须使用 HTTPS")
    headers = httpx.Headers(upload.get("headers") or {})
    # 即使服务端误返回这些头，也不能把浏览器或官网的认证信息交给存储服务。
    for name in ("Authorization", "Cookie", "Host", "Origin", "Referer", "X-CSRF-Token"):
        headers.pop(name, None)
    return target, same_origin, headers


async def put_upload(client, upload, package, progress):
    target, same_origin, headers = upload_target(client, upload)
    headers["Content-Length"] = str(package.bytes)
    tokens = await asyncio.to_thread(client.store.read) if same_origin else None

    async def content():
        source = await durable_io(package.path.open, "rb")
        sent, last_percent = 0, -1
        try:
            while chunk := await durable_io(source.read, 128 * 1024):
                sent += len(chunk)
                yield chunk
                percent = min(100, sent * 100 // package.bytes)
                if percent != last_percent:
                    progress("正在上传模型", percent)
                    last_percent = percent
        finally:
            await durable_io(source.close)

    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as http:
        async def send(current):
            request_headers = headers.copy()
            if same_origin and current:
                request_headers["Authorization"] = f"Bearer {current['access_token']}"
            return await http.put(target, headers=request_headers, content=content())

        response = await send(tokens)
        if response.status_code == 401 and same_origin and tokens:
            tokens = await client.refresh_tokens(http, tokens)
            response = await send(tokens)
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("上传服务返回了不支持的重定向")
