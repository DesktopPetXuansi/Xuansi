"""把选择、自动准备和实际使用串起来；独立预览保留为可选操作。"""

import logging

from PySide6.QtCore import QObject, QTimer

from .appearance_apply import AppearanceApply
from .appearance_hub import candidate_key
from .appearance_import import AppearanceCandidate
from .appearance_sources import AppearanceSources

LOG = logging.getLogger(__name__)


class AppearanceFlow(QObject):
    def __init__(self, owner, view, platform, *, on_applied, is_saving=lambda: False):
        super().__init__(view)
        self.owner, self.view, self.platform = owner, view, platform
        self.on_applied, self.is_saving = on_applied, is_saving
        self.sources = AppearanceSources(platform, self)
        self.applying = AppearanceApply(owner, self)
        self._signature = None
        self._restore_pending = self._restoring = ''
        self._authorizing, self._login_error = False, ''
        self._closed = False
        self._direct_requested = False
        self._pending_use = self._using_candidate = None
        platform.appearance_managed = True
        platform.appearance_requested.connect(self.use_resource)
        view.import_requested.connect(self.sources.local)
        view.online_requested.connect(self.sources.discover)
        view.mine_requested.connect(self.sources.mine)
        view.choice_requested.connect(self.choose)
        view.choice_use_requested.connect(lambda choice: self.choose(choice, direct=True))
        view.use_requested.connect(self.use)
        view.default_requested.connect(lambda: view.show_candidate(AppearanceCandidate('DEFAULT', '默认玄司')))
        view.share_requested.connect(platform.open_upload)
        view.more_requested.connect(lambda: owner.panel.open_section('resources'))
        view.login_requested.connect(self.login)
        view.cancel_requested.connect(self.cancel)
        self.sources.candidate_ready.connect(self.candidate_ready)
        self.sources.choices_ready.connect(lambda mode, choices: view.show_choices('online' if mode == 'discover' else mode, choices))
        self.sources.status_changed.connect(view.status.setText)
        self.sources.failed.connect(self.failed)
        self.sources.busy_changed.connect(self.refresh_busy)
        self.applying.busy_changed.connect(self.apply_busy)
        self.applying.finished.connect(self.applied)
        platform.operation_finished.connect(self.restore_when_idle)
        platform.operation_finished.connect(self.source_finished)
        platform.operation_failed.connect(self.login_failed)
        platform.busy_changed.connect(self.schedule_restore)
        owner.runtime.platform_settings_saved.connect(self.login_saved)
        owner.runtime.settings_saved.connect(self.schedule_use)

    def present(self):
        settings = self.owner.settings
        signature = (settings.avatar_image, settings.platform_model_version)
        if signature == self._signature:
            return
        self._signature = signature
        if settings.avatar_image:
            kind = 'ANIMATION' if settings.avatar_image.endswith('.apng') else 'IMAGE'
            self.view.set_current(AppearanceCandidate(kind, '本地形象', settings.avatar_image))
        elif settings.platform_model_version:
            self.view.set_current(AppearanceCandidate('MODEL', 'Live2D形象'), preview=False)
            self._restore_pending = settings.platform_model_version
            self.restore_when_idle()
        else:
            self.view.set_current(AppearanceCandidate('DEFAULT', '默认玄司'))
        self.refresh_busy()

    def schedule_restore(self, busy):
        # 使用任务完成事件衔接，不轮询；等待当前 worker 真正退场再读当前模型。
        if not busy and self._restore_pending and not self._closed:
            QTimer.singleShot(0, self.restore_when_idle)
        if not busy and self._authorizing and not self._closed:
            # 等线程退场及同轮保存回执处理完，再在原页面给出最终授权结果。
            QTimer.singleShot(0, self.login_finished)
        if not busy:
            self.schedule_use()

    def login(self):
        if self._closed or self.sources.busy or self.is_saving():
            return
        self._authorizing, self._login_error = True, ''
        self.platform.login()
        self.view.status.setText('请在浏览器完成官网登录，完成后回到这里继续下载。也可取消操作。')
        self.refresh_busy()

    def cancel(self):
        self._direct_requested = False
        pending, self._pending_use = self._pending_use, None
        if self._authorizing:
            self.platform.cancel()
        else:
            self.sources.cancel()
        if pending is not None:
            self.view.status.setText('已取消使用，当前形象保持不变。')
        self.refresh_busy()

    def login_failed(self, command, error):
        if self._authorizing and command == 'login':
            self._login_error = error

    def login_saved(self, settings, error):
        if self._authorizing and error:
            self._login_error = '官网地址未能保存，请稍后重新连接。'
        self.schedule_use()

    def login_finished(self):
        if self._closed or not self._authorizing or self.platform.busy or self.platform.worker is not None:
            return
        self._authorizing = False
        self.view.status.setText(self._login_error or '官网已连接，选中形象后点击“使用这个形象”。')
        self.refresh_busy()

    def restore_when_idle(self, *_):
        if (self._closed or not self._restore_pending or self.sources.busy
                or self.applying.busy or self._pending_use is not None):
            return
        self._restoring, self._restore_pending = self._restore_pending, ''
        self.sources.installed(self._restoring)

    def choose(self, choice, *, direct=False):
        if self._closed or self.view.busy or self.is_saving():
            return
        self._direct_requested = direct
        if isinstance(choice, dict):
            self.sources.download(choice)
        else:
            self.candidate_ready(choice)
        # 来源拒绝启动时不保留使用意图，后续导入不能误触发自动应用。
        if self._direct_requested and not self.sources.active:
            self._direct_requested = False
        self.refresh_busy()

    def candidate_ready(self, candidate):
        if self._closed:
            return
        if self._restoring and candidate.version_id == self._restoring:
            self._restoring = ''
            self.view.set_current(candidate)
        elif self._direct_requested:
            self._direct_requested = False
            self._pending_use = candidate
            self.view.show_candidate(candidate, preview=False)
            self.resume_use()
        else:
            self.view.show_candidate(candidate)
        self.refresh_busy()

    def source_finished(self, *_):
        if self._closed:
            return
        if not self.sources.active:
            self._direct_requested = False
        self.refresh_busy()

    def schedule_use(self, *_):
        if not self._closed:
            # 等设置保存和 worker 退场的同轮回执处理完，不轮询也不阻塞界面。
            QTimer.singleShot(0, self.resume_use)

    def resume_use(self):
        if self._closed:
            return
        if self._pending_use is not None:
            if self.sources.busy or self.is_saving() or self.applying.busy:
                self.view.status.setText('形象已准备好，等待当前操作完成后自动使用；也可以取消。')
                self.refresh_busy()
                return
            candidate, self._pending_use = self._pending_use, None
            if candidate_key(candidate) == candidate_key(self.view.current):
                self.view.status.setText('已经在使用这个形象，无需再次保存。')
            else:
                self._apply(candidate)
        self.refresh_busy()

    def _apply(self, candidate):
        self._using_candidate = candidate
        self.applying.use(candidate)

    def failed(self, error):
        self._direct_requested, self._pending_use = False, None
        if self._restoring:
            # 读取失败不缓存为已恢复；下次打开可重试，恢复默认也仍是一项真实变更。
            self._signature = None
        self._restoring = ''
        if '401' in error or '403' in error:
            error = '此资源需要官网授权。请点击“登录官网”，完成后再使用。'
        self.view.status.setText(error)
        self.refresh_busy()

    def refresh_busy(self, *_):
        active = self.sources.active
        # 列表、下载失败和取消不改变已预览候选；有效性只由真实预览回执更新。
        busy = (self.sources.busy or self.applying.busy or self.is_saving()
                or self._direct_requested or self._pending_use is not None)
        self.view.set_busy(busy, cancellable=active or self._pending_use is not None
                           or self._authorizing and self.platform.worker is not None)

    def apply_busy(self, busy):
        self.platform.appearance_busy = busy
        self.platform.set_busy(busy or self.platform.worker is not None
                               or self.platform.pending_settings is not None or self.platform.shutting_down)
        self.refresh_busy()
        if busy:
            self.view.status.setText('正在使用并保存这个形象…')

    def use(self, candidate):
        if not self._closed and self.view.ready and not self.sources.busy and not self.is_saving():
            self._apply(candidate)

    def use_resource(self, candidate):
        """旧资源页的明确应用按钮复用事务，只有真实桌宠试载成功才发使用回执。"""
        if (self._closed or self.applying.busy or self.sources.active or self.is_saving()
                or self._direct_requested or self._pending_use is not None):
            self.platform.status.setText('请先等待当前形象操作完成。')
            return
        self.view.show_candidate(candidate)
        self._apply(candidate)
        LOG.info('官网资源应用已转交统一形象事务 kind=%s', candidate.kind)

    def applied(self, settings, error):
        candidate, self._using_candidate = self._using_candidate, None
        self.platform.status.setText(error or '形象已成功更换并保存。')
        if error:
            self.view.status.setText(error)
        else:
            self._signature = (settings.avatar_image, settings.platform_model_version)
            self.view.applied(candidate)
            self.owner.panel.form.refresh()
            self.on_applied()
            LOG.info('统一形象流程已完成并更新当前使用状态')
        self.refresh_busy()

    def close(self):
        self._closed = True
        self._direct_requested = False
        self._pending_use = self._using_candidate = None
        self.sources.close()
        self.applying.close()
