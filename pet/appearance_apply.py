"""保存成功后切换形象；试载失败时只恢复本次修改的三个选择字段。"""

import logging

from PySide6.QtCore import QObject, Signal

LOG = logging.getLogger(__name__)
SELECTION_FIELDS = ("avatar_image", "platform_model_version", "platform_expression_version")


class AppearanceApply(QObject):
    """由界面线程协调异步保存和真实桌宠试载，不接管其他配置。"""

    finished = Signal(object, str)
    used = Signal(object)
    busy_changed = Signal(bool)

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self._stage = ""
        self._closed = False
        self._candidate = None
        self._original = {}
        owner.runtime.platform_settings_saved.connect(self._saved)

    @property
    def busy(self):
        return bool(self._stage)

    def use(self, candidate):
        if self._closed or self.busy:
            return
        if (candidate.kind not in {"DEFAULT", "IMAGE", "ANIMATION", "MODEL"}
                or (candidate.kind in {"IMAGE", "ANIMATION"} and not candidate.image_id)
                or (candidate.kind == "MODEL" and (not candidate.prepared or not candidate.version_id))):
            self.finished.emit(None, "请选择一个可用的桌宠形象。")
            return
        self._candidate = candidate
        self._original = {name: getattr(self.owner.settings, name) for name in SELECTION_FIELDS}
        changes = {
            "avatar_image": candidate.image_id if candidate.kind in {"IMAGE", "ANIMATION"} else "",
            "platform_model_version": candidate.version_id if candidate.kind == "MODEL" else "",
            "platform_expression_version": "",
        }
        self._stage = "save"
        self.busy_changed.emit(True)
        LOG.info("开始保存形象选择 kind=%s", candidate.kind)
        self._persist(changes)

    def _persist(self, changes):
        try:
            self.owner.runtime.persist_platform(changes)
        except Exception as exc:
            # 调度本身失败也遵循相同事务出口，避免按钮一直处于忙碌状态。
            LOG.warning("形象选择保存调度失败 type=%s", type(exc).__name__)
            self._saved(self.owner.settings, "形象选择保存失败，请稍后重试。")

    def _update_settings(self, settings):
        self.owner.settings = self.owner.panel.settings = settings

    def _saved(self, settings, error):
        if self._closed or not self.busy:
            return
        if self._stage == "rollback":
            if error:
                LOG.warning("形象试载失败，选择记录恢复失败")
                self._finish(None, "原形象仍在显示，但选择记录恢复失败；重启前请重新选择原形象。")
            else:
                self._update_settings(settings)
                LOG.info("形象试载失败后已恢复原选择记录")
                self._finish(None, "未更换，原形象继续使用。请检查文件是否完整或选择其他形象。")
            return
        if error:
            LOG.warning("形象选择保存失败，未修改当前形象")
            self._finish(None, error)
            return
        self._update_settings(settings)
        try:
            candidate = self._candidate
            if candidate.kind == "MODEL":
                self.owner.avatar.select_platform_model(candidate.version_id, candidate.prepared)
            else:
                image_id = candidate.image_id if candidate.kind in {"IMAGE", "ANIMATION"} else ""
                self.owner.avatar.set_image(image_id, force=True, strict=True)
        except Exception as exc:
            # 头像自身先试载再替换；失败时原头像仍在，只需恢复持久化选择。
            LOG.warning("形象试载失败，开始恢复原选择 type=%s", type(exc).__name__)
            self._stage = "rollback"
            self._persist(self._original)
            return
        LOG.info("形象更换并保存成功 kind=%s", self._candidate.kind)
        self.used.emit(self._candidate)
        self._finish(settings, "")

    def _finish(self, settings, error):
        self._stage = ""
        self._candidate = None
        self._original = {}
        self.busy_changed.emit(False)
        self.finished.emit(settings, error)

    def close(self):
        """关闭后断开回执，不再访问即将释放的窗口及原生渲染控件。"""
        if self._closed:
            return
        self._closed = True
        self.owner.runtime.platform_settings_saved.disconnect(self._saved)
        self._stage = ""
        self._candidate = None
        self._original = {}
        LOG.info("形象更换协调器已关闭，忽略后续保存回执")
