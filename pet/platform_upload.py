"""从本地模型到已校验官网资源的一次上传，不要求用户手工创建资源或压缩包。"""

import asyncio
import logging
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

import httpx

from .platform_model_package import build_model_package
from .platform_resources import identifier
from .platform_upload_transport import put_upload

LOG = logging.getLogger(__name__)
DEFAULT_LICENSE = "仅个人使用，禁止再分发"


class UploadError(ValueError):
    """可直接显示的本地模型与上传状态说明，不包含凭据或请求正文。"""


async def _package(source, output, progress):
    cancel = threading.Event()
    pending = asyncio.create_task(asyncio.to_thread(
        build_model_package, source, output, lambda percent: progress("正在整理模型文件", percent), cancel))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        cancel.set()
        # 等文件线程退出后再清理临时目录，避免磁盘线程继续写入已删除位置。
        await asyncio.gather(pending, return_exceptions=True)
        raise
    except ValueError as exc:
        raise UploadError(str(exc)) from exc


async def _wait_ready(client, upload_id, resource_id, version_id, progress):
    progress("文件已上传，正在等待官网校验", 0)
    async with asyncio.timeout(300):
        while True:
            upload = await client.request("GET", f"/uploads/{upload_id}")
            if upload["status"] == "READY":
                return
            if upload["status"] in {"FAILED", "CANCELLED", "EXPIRED"}:
                version = await client.request("GET", f"/resources/{resource_id}/versions/{version_id}")
                errors = version.get("validationReport", {}).get("errors", [])
                details = "；".join(item[:200] for item in errors[:3] if isinstance(item, str))
                raise UploadError(details or "模型校验未通过，请检查模型运行文件是否完整")
            await asyncio.sleep(1)


async def finalize_upload(client, progress=None):
    """完成步骤按同一资源重试；网络失败不会再次创建资源或重传文件。"""
    result = client.pending_model_upload
    resource_id, version_id = identifier(result["resourceId"]), identifier(result["resourceVersionId"])
    progress = progress or (lambda _phase, _percent: None)
    progress("正在将模型加入资源库", 100)
    try:
        await client.request("PATCH", f"/resources/{resource_id}", {"currentVersionId": version_id})
        await client.request("PUT", f"/me/library/{resource_id}", {"pinnedVersionId": version_id})
    except (httpx.HTTPError, ValueError) as exc:
        raise UploadError("模型文件已上传并校验完成，但加入资源库失败；请确认连接账号后点击重试完成，无需再次上传。") from exc
    client.pending_model_upload = None
    LOG.info("客户端模型上传完成 resource=%s version=%s", resource_id, version_id)
    progress("上传完成，模型已加入官网资源库", 100)
    return result


async def upload_model(client, source, metadata=None, progress=None):
    tokens = await asyncio.to_thread(client.store.read)
    if not tokens or "resources:write" not in str(tokens.get("scope", "")).split():
        raise UploadError("请先连接官网并允许上传权限")
    progress = progress or (lambda _phase, _percent: None)
    profile = await client.request("GET", "/me")
    if not profile.get("emailVerified"):
        raise UploadError("请先在官网验证邮箱，再上传模型")
    metadata = dict(metadata or {})
    upload_id, ready = None, False
    # 目录由本次调用独占，始终等待所有文件线程退出后才清理。
    with tempfile.TemporaryDirectory(prefix="pet-model-upload-") as temporary:
        package = await _package(source, Path(temporary) / "model.zip", progress)
        body = {"kind": "MODEL", "name": metadata.get("name") or package.name,
                "author": metadata.get("author") or profile["displayName"],
                "license": metadata.get("license") or DEFAULT_LICENSE,
                "description": metadata.get("description", "")}
        version = metadata.get("version") or "1.0.0"
        if not all(isinstance(body[field], str) and body[field].strip()
                   for field in ("name", "author", "license")):
            raise UploadError("请填写模型名称、作者与使用许可")
        resource = await client.request("POST", "/resources", body)
        resource_id = identifier(resource["id"])
        try:
            created = await client.request("POST", f"/resources/{resource_id}/versions", {
                "version": version, "filename": "model.zip", "expectedBytes": package.bytes,
                "entrypoint": package.entrypoint, "minimumClientVersion": "",
            })
            upload_id = identifier(created["upload"]["id"])
            version_id = identifier(created["version"]["id"])
            await put_upload(client, created["upload"], package, progress)
            completion_key = str(uuid4())
            await client.request("POST", f"/uploads/{upload_id}/completion", {},
                                 headers={"Idempotency-Key": completion_key})
            await _wait_ready(client, upload_id, resource_id, version_id, progress)
            ready = True
            client.pending_model_upload = {"resourceId": resource_id, "resourceVersionId": version_id, "name": body["name"]}
            return await finalize_upload(client, progress)
        except (Exception, asyncio.CancelledError):
            if upload_id and not ready:
                try:
                    async with asyncio.timeout(15):
                        await client.request("DELETE", f"/uploads/{upload_id}")
                except (Exception, asyncio.CancelledError):
                    LOG.warning("上传取消未确认，官网将按到期规则清理 upload=%s", upload_id)
            raise
