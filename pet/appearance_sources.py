"""统一形象来源；复用平台后台队列，完成退场后才交付待预览候选。"""

import asyncio
import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, Signal

from . import appearance, platform_resources
from .appearance_cache import CACHE_FAILURE, cache_exists, cached_candidate
from .appearance_import import AppearanceCandidate, import_appearance, installed_candidate
from .platform_resources import installed_resources

LOG = logging.getLogger(__name__)
APPEARANCE_KINDS = {"MODEL", "IMAGE", "ANIMATION"}


@dataclass(frozen=True)
class SourceFailure:
    """后台明确的业务提示随完成回执返回，不经过通用网络错误改写。"""

    message: str


class AppearanceSources(QObject):
    candidate_ready = Signal(object)
    choices_ready = Signal(str, object)
    failed = Signal(str)
    status_changed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, platform, parent=None, *, image_directory=None, resource_root=None):
        super().__init__(parent)
        self.platform = platform
        self.image_directory = Path(image_directory) if image_directory is not None else appearance.DIRECTORY
        self.resource_root = Path(resource_root) if resource_root is not None else platform_resources.RESOURCE_ROOT
        self._closed = False
        self._command = ""
        self._result = None
        self._error = ""
        self._cancelled = False
        self._cancel_event = None
        self._last_busy = False
        platform.operation_completed.connect(self._completed)
        platform.operation_failed.connect(self._failed)
        platform.operation_finished.connect(self._finished)
        platform.busy_changed.connect(self._busy_changed)

    @property
    def busy(self):
        return not self._closed and bool(self._command or self.platform.busy)

    @property
    def active(self):
        return not self._closed and bool(self._command)

    def _busy_changed(self, _busy=False):
        if not self._closed and self.busy != self._last_busy:
            self._last_busy = self.busy
            self.busy_changed.emit(self.busy)

    def _start(self, command, operation, message):
        if self._closed or self.busy:
            return
        self._command = "appearance-" + command
        self._result, self._error, self._cancelled = None, "", False
        if not self.platform.start(self._command, operation):
            self._command = ""
            self._busy_changed()
            return
        self._cancel_event = self.platform.worker.cancel_requested
        self._busy_changed()
        if not self._closed:
            self.status_changed.emit(message)
        LOG.info("形象来源任务已开始 command=%s", command)

    def local(self, path):
        async def operation():
            worker = self.platform.worker
            try:
                return await asyncio.to_thread(import_appearance, path, cancel=worker.cancel_requested,
                                               image_directory=self.image_directory, resource_root=self.resource_root)
            except ValueError as exc:
                # 本机导入器给出的格式/缺文件提示可直接帮助用户纠正选择。
                return SourceFailure(str(exc))
        self._start("local", operation, "正在准备你选择的形象…")

    def installed(self, version_id):
        async def operation():
            return await asyncio.to_thread(installed_candidate, version_id,
                                           image_directory=self.image_directory, resource_root=self.resource_root)
        self._start("installed", operation, "正在准备这个形象…")

    def mine(self):
        async def operation():
            return await asyncio.to_thread(self._mine)
        self._start("mine", operation, "正在整理我的形象…")

    def _mine(self):
        result = [AppearanceCandidate("DEFAULT", "玄司 · 默认形象")]
        image_ids = set()
        for manifest in installed_resources(self.resource_root):
            if manifest["kind"] not in APPEARANCE_KINDS:
                continue
            try:
                candidate = installed_candidate(manifest["resourceVersionId"],
                                                image_directory=self.image_directory, resource_root=self.resource_root)
            except (ValueError, KeyError, OSError, TypeError):
                LOG.warning("我的形象列表忽略不可用的已安装形象")
                continue
            if candidate.image_id and candidate.image_id in image_ids:
                continue
            if candidate.image_id:
                image_ids.add(candidate.image_id)
            if re.fullmatch(r"[0-9a-f]{64}(?:\.(?:png|apng))?", candidate.name):
                candidate = replace(candidate, name=f"已下载形象 {len(result)}")
            result.append(candidate)
        if self.image_directory.is_dir():
            for path in sorted(self.image_directory.iterdir()):
                if (not re.fullmatch(r"[0-9a-f]{64}\.(png|apng)", path.name)
                        or path.name in image_ids or path.is_symlink() or path.is_junction() or not path.is_file()):
                    continue
                try:
                    with Image.open(path) as image:
                        animated = getattr(image, "n_frames", 1) > 1
                except (OSError, ValueError, Image.DecompressionBombError):
                    LOG.warning("我的形象列表忽略不可读取的本机图片")
                    continue
                kind, label = ("ANIMATION", "本地动图") if animated else ("IMAGE", "本地图片")
                result.append(AppearanceCandidate(kind, f"{label} {len(result)}", path.name))
                image_ids.add(path.name)
        return result

    def discover(self):
        async def operation():
            resources = await self.platform.api().request("GET", "/resources?limit=100", anonymous=True)
            return [item for item in resources if item["kind"] in APPEARANCE_KINDS]
        self._start("discover", operation, "正在寻找可以使用的形象…")

    def download(self, resource):
        if self._closed or self.busy:
            return
        if resource.get("kind") not in APPEARANCE_KINDS:
            self.failed.emit("请选择图片、动图或桌宠模型；动作和表情不能单独作为形象。")
            return
        async def operation():
            client = self.platform.api()
            try:
                platform_resources.identifier(resource["id"])
            except (ValueError, KeyError, TypeError, AttributeError):
                return SourceFailure("这个形象的资源标识无效，请刷新官网形象列表后重试。")
            versions = await client.request("GET", f"/resources/{resource['id']}/versions")
            # 官网按创建时间倒序返回，首个通过校验的版本即最新可用版本。
            version = next((item for item in versions if item["validationStatus"] == "READY"
                            and item.get("compatibilityStatus") != "INCOMPATIBLE"), None)
            if version is None:
                return SourceFailure("这个形象暂时没有可下载的版本，请选择其他形象或稍后再试。")
            try:
                platform_resources.identifier(version["id"])
                if self._cancel_event and self._cancel_event.is_set():
                    raise asyncio.CancelledError
                cached = await asyncio.to_thread(cache_exists, version["id"], self.resource_root)
                if cached:
                    manifest = await client.request(
                        "GET", f"/resources/{resource['id']}/versions/{version['id']}/manifest")
                    candidate = await asyncio.to_thread(
                        cached_candidate, manifest, resource, version["id"],
                        image_directory=self.image_directory, resource_root=self.resource_root)
                    return replace(candidate, name=resource.get("name") or candidate.name)
            except (ValueError, KeyError, OSError, TypeError, AttributeError):
                LOG.warning("官网形象缓存检查失败，保留文件并拒绝使用")
                return SourceFailure(CACHE_FAILURE)
            await client.install(resource["id"], version["id"], root=self.resource_root)
            candidate = await asyncio.to_thread(installed_candidate, version["id"],
                                                image_directory=self.image_directory, resource_root=self.resource_root)
            return replace(candidate, name=resource.get("name") or candidate.name)
        self._start("download", operation, "正在准备形象，未下载时会自动下载…")

    def _completed(self, command, result):
        if not self._closed and command == self._command:
            self._result = result

    def _failed(self, command, error):
        if not self._closed and command == self._command:
            self._error = error

    def _finished(self, command):
        if self._closed or command != self._command:
            return
        cancelled = self._cancelled or bool(self._cancel_event and self._cancel_event.is_set())
        result, error = self._result, self._error
        self._command, self._result, self._error = "", None, ""
        self._cancel_event = None
        self._busy_changed()
        if self._closed:
            return
        # 必须等平台 worker 真正退出，避免候选预览或后续选择被后台队列拒绝。
        if cancelled:
            self.status_changed.emit("已取消，当前形象保持不变。")
        elif error:
            self.failed.emit(error)
        elif isinstance(result, SourceFailure):
            self.failed.emit(result.message)
        elif command in {"appearance-mine", "appearance-discover"}:
            self.choices_ready.emit(command.removeprefix("appearance-"), result)
        elif isinstance(result, AppearanceCandidate):
            self.candidate_ready.emit(result)
        else:
            self.failed.emit("这个形象暂时无法使用，请重新选择。")
        LOG.info("形象来源任务已结束 command=%s cancelled=%s", command, cancelled)

    def cancel(self):
        if self._closed or not self._command:
            return
        self._cancelled = True
        self.platform.cancel()
        self.status_changed.emit("正在取消，请稍候…")

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._command:
            self.platform.cancel()
        for signal, slot in (
            (self.platform.operation_completed, self._completed),
            (self.platform.operation_failed, self._failed),
            (self.platform.operation_finished, self._finished),
            (self.platform.busy_changed, self._busy_changed),
        ):
            signal.disconnect(slot)
        self._command, self._result = "", None
        self._cancel_event = None
        LOG.info("形象来源协调器已关闭，忽略后续后台回执")
