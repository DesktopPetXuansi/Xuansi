"""模型设置后台任务；取消传播到异步验证，信号只返回受控错误。"""

import asyncio
import logging
import threading

from PySide6.QtCore import QObject, QRunnable, Signal

LOG = logging.getLogger(__name__)


class AIResults(QObject):
    validation = Signal(str, object, str)
    device = Signal(int, object, str)


class ValidateProfile(QRunnable):
    def __init__(self, signals, profile, key, request_id):
        super().__init__()
        self.signals, self.profile, self.key = signals, profile, key
        self.request_id = request_id
        self.cancelled = threading.Event()
        self.loop = self.task = None

    def cancel(self):
        self.cancelled.set()
        if self.loop is not None and self.task is not None:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass  # 已关闭的事件循环无需再次取消。

    async def _validate(self):
        from .ai.validation import validate_profile

        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        if self.cancelled.is_set():
            raise asyncio.CancelledError
        return await validate_profile(self.profile, self.key)

    def run(self):
        try:
            result = asyncio.run(self._validate())
            if not self.cancelled.is_set():
                self.signals.validation.emit(self.request_id, result, "")
        except asyncio.CancelledError:
            LOG.info("模型配置验证已取消")
        except Exception:
            # 底层意外异常也不能把 URL、Key 或响应正文带入界面/日志。
            LOG.warning("模型配置验证未完成")
            if not self.cancelled.is_set():
                self.signals.validation.emit(self.request_id, None, "验证未完成，请检查配置、Key、额度和网络后重试。")
        finally:
            self.key = None


class ProbeDevice(QRunnable):
    def __init__(self, signals, generation, model_dir):
        super().__init__()
        self.signals, self.generation, self.model_dir = signals, generation, model_dir

    def run(self):
        from .ai.device import probe_device
        from .config import ROOT

        try:
            report = probe_device(ROOT, self.model_dir)
            self.signals.device.emit(self.generation, report, "")
        except Exception:
            LOG.warning("设置页环境重新检测未完成")
            self.signals.device.emit(self.generation, None, "环境检测失败，状态未知；可重新检测。")
