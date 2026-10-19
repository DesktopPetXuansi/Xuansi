"""把来源、独立预览和保存事务串成一条可见的换形象流程。"""

import logging

from PySide6.QtCore import QObject, QTimer

from .appearance_apply import AppearanceApply
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
        platform.appearance_managed = True
        platform.appearance_requested.connect(self.use_resource)
        view.import_requested.connect(self.sources.local)
        view.online_requested.connect(self.sources.discover)
        view.mine_requested.connect(self.sources.mine)
        view.choice_requested.connect(self.choose)
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
        platform.operation_failed.connect(self.login_failed)
        platform.busy_changed.connect(self.schedule_restore)
        owner.runtime.platform_settings_saved.connect(self.login_saved)

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

    def login(self):
        if self._closed or self.sources.busy or self.is_saving():
            return
        self._authorizing, self._login_error = True, ''
        self.platform.login()
        self.view.status.setText('请在浏览器完成官网登录，完成后回到这里继续下载。也可取消操作。')
        self.refresh_busy()

    def cancel(self):
        if self._authorizing:
            self.platform.cancel()
        else:
            self.sources.cancel()

    def login_failed(self, command, error):
        if self._authorizing and command == 'login':
            self._login_error = error

    def login_saved(self, settings, error):
        if self._authorizing and error:
            self._login_error = '官网地址未能保存，请稍后重新连接。'

    def login_finished(self):
        if self._closed or not self._authorizing or self.platform.busy or self.platform.worker is not None:
            return
        self._authorizing = False
        self.view.status.setText(self._login_error or '官网已连接，可以选择形象并点击“下载并预览”。')
        self.refresh_busy()

    def restore_when_idle(self, *_):
        if self._closed or not self._restore_pending or self.sources.busy or self.applying.busy:
            return
        self._restoring, self._restore_pending = self._restore_pending, ''
        self.sources.installed(self._restoring)

    def choose(self, choice):
        if isinstance(choice, dict):
            self.sources.download(choice)
        else:
            self.view.show_candidate(choice)

    def candidate_ready(self, candidate):
        if self._restoring and candidate.version_id == self._restoring:
            self._restoring = ''
            self.view.set_current(candidate)
        else:
            self.view.show_candidate(candidate)
        self.refresh_busy()

    def failed(self, error):
        if self._restoring:
            # 读取失败不缓存为已恢复；下次打开可重试，恢复默认也仍是一项真实变更。
            self._signature = None
        self._restoring = ''
        if '401' in error or '403' in error:
            error = '下载需要官网授权。请点击“登录官网”，完成后再下载预览。'
        self.view.status.setText(error)
        self.view.refresh_buttons()

    def refresh_busy(self, *_):
        active = self.sources.active
        # 列表、下载失败和取消不改变已预览候选；有效性只由真实预览回执更新。
        busy = self.sources.busy or self.applying.busy or self.is_saving()
        self.view.set_busy(busy, cancellable=active or self._authorizing and self.platform.worker is not None)

    def apply_busy(self, busy):
        self.platform.appearance_busy = busy
        self.platform.set_busy(busy or self.platform.worker is not None
                               or self.platform.pending_settings is not None or self.platform.shutting_down)
        self.refresh_busy()
        if busy:
            self.view.status.setText('正在使用并保存这个形象…')

    def use(self, candidate):
        if not self._closed and self.view.ready and not self.sources.busy and not self.is_saving():
            self.applying.use(candidate)

    def use_resource(self, candidate):
        """旧资源页的明确应用按钮复用事务，只有真实桌宠试载成功才发使用回执。"""
        if self._closed or self.applying.busy or self.sources.active or self.is_saving():
            self.platform.status.setText('请先等待当前形象操作完成。')
            return
        self.view.show_candidate(candidate)
        self.applying.use(candidate)
        LOG.info('官网资源应用已转交统一形象事务 kind=%s', candidate.kind)

    def applied(self, settings, error):
        self.platform.status.setText(error or '形象已成功更换并保存。')
        if error:
            self.view.status.setText(error)
        else:
            self._signature = (settings.avatar_image, settings.platform_model_version)
            self.view.applied(self.view.candidate)
            self.owner.panel.form.refresh()
            self.on_applied()
            LOG.info('统一形象流程已完成并更新当前使用状态')
        self.refresh_busy()

    def close(self):
        self._closed = True
        self.sources.close()
        self.applying.close()
