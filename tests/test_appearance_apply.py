"""形象更换事务回归；全部使用合成配置，不创建真实渲染资源。"""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from pet.appearance_apply import AppearanceApply
from pet.config import Settings


class Runtime(QObject):
    platform_settings_saved = Signal(object, str)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.calls = []

    def persist_platform(self, changes):
        self.calls.append(changes)

    def reply(self, error="", **concurrent):
        # 模拟生产运行时持锁后以最新配置合并，不能整份覆盖其他页面的设置。
        self.settings = replace(self.settings, **concurrent)
        if not error:
            self.settings = replace(self.settings, **self.calls[-1])
        self.platform_settings_saved.emit(self.settings, error)


@pytest.fixture
def transaction(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    settings = replace(Settings(), avatar_image="old.png", platform_model_version="old-model",
                       platform_expression_version="old-expression")
    owner = SimpleNamespace(settings=settings, panel=SimpleNamespace(settings=settings),
                            runtime=Runtime(settings), avatar=Mock())
    operation = AppearanceApply(owner)
    replies, busy = [], []
    operation.finished.connect(lambda settings, error: replies.append((settings, error)))
    operation.busy_changed.connect(busy.append)
    yield owner, operation, replies, busy
    operation.close()
    app.processEvents()


def candidate(kind="IMAGE"):
    prepared = ({"resourceVersionId": "new-model", "kind": "MODEL"}, "model.model3.json")
    return SimpleNamespace(kind=kind, name="测试形象", image_id="new.png" if kind != "DEFAULT" else "",
                           prepared=prepared if kind == "MODEL" else None,
                           version_id="new-model" if kind == "MODEL" else "")


def test_save_failure_never_changes_avatar(transaction):
    owner, operation, replies, busy = transaction
    before = owner.settings
    operation.use(candidate())
    owner.avatar.set_image.assert_not_called()
    owner.runtime.reply("磁盘已满")
    assert owner.avatar.mock_calls == []
    assert owner.settings is before and owner.panel.settings is before
    assert replies == [(None, "磁盘已满")]
    assert busy == [True, False] and not operation.busy


@pytest.mark.parametrize("kind", ["IMAGE", "ANIMATION", "DEFAULT", "MODEL"])
def test_save_then_apply_success(transaction, kind):
    owner, operation, replies, busy = transaction
    selected = candidate(kind)
    operation.use(selected)
    assert owner.avatar.mock_calls == []
    owner.runtime.reply()
    if kind == "MODEL":
        owner.avatar.select_platform_model.assert_called_once_with(selected.version_id, selected.prepared)
        owner.avatar.set_image.assert_not_called()
    else:
        owner.avatar.set_image.assert_called_once_with(selected.image_id, force=True, strict=True)
        owner.avatar.select_platform_model.assert_not_called()
    assert owner.settings is owner.panel.settings is owner.runtime.settings
    assert owner.settings.platform_expression_version == ""
    assert replies == [(owner.settings, "")] and busy == [True, False]


@pytest.mark.parametrize("kind", ["IMAGE", "MODEL", "DEFAULT"])
def test_load_failure_restores_only_original_appearance_fields(transaction, kind):
    owner, operation, replies, busy = transaction
    before = owner.settings
    owner.avatar.set_image.side_effect = ValueError("合成试载失败")
    owner.avatar.select_platform_model.side_effect = ValueError("合成试载失败")
    operation.use(candidate(kind))
    owner.runtime.reply(name="并发更新的名字")
    assert operation.busy and not replies
    assert owner.runtime.calls[-1] == {key: getattr(before, key) for key in (
        "avatar_image", "platform_model_version", "platform_expression_version")}
    owner.runtime.reply(interval=80)
    assert owner.settings.name == "并发更新的名字" and owner.settings.interval == 80
    assert owner.settings.avatar_image == before.avatar_image
    assert owner.settings.platform_expression_version == before.platform_expression_version
    assert owner.panel.settings is owner.settings
    assert replies[0][0] is None and "原形象继续使用" in replies[0][1]
    assert busy == [True, False]


def test_rollback_failure_reports_that_saved_selection_was_not_restored(transaction):
    owner, operation, replies, busy = transaction
    owner.avatar.set_image.side_effect = RuntimeError("合成试载失败")
    operation.use(candidate())
    owner.runtime.reply()
    owner.runtime.reply("磁盘已满")
    assert len(owner.runtime.calls) == 2
    assert replies[0][0] is None and "恢复失败" in replies[0][1]
    assert "原形象" in replies[0][1] and "重启" in replies[0][1]
    assert busy == [True, False]


def test_concurrent_unrelated_settings_are_preserved(transaction):
    owner, operation, replies, _ = transaction
    operation.use(candidate())
    assert set(owner.runtime.calls[0]) == {
        "avatar_image", "platform_model_version", "platform_expression_version"}
    owner.runtime.reply(name="其他页面新名字", interval=90, platform_url="http://localhost:9999")
    assert owner.settings.name == "其他页面新名字" and owner.settings.interval == 90
    assert owner.settings.platform_url == "http://localhost:9999"
    assert replies == [(owner.runtime.settings, "")]


def test_repeated_click_and_unrelated_receipt_do_not_start_extra_work(transaction):
    owner, operation, replies, _ = transaction
    owner.runtime.platform_settings_saved.emit(owner.settings, "")
    operation.use(candidate())
    operation.use(candidate("DEFAULT"))
    assert len(owner.runtime.calls) == 1 and not replies
    owner.runtime.reply()
    assert len(replies) == 1


def test_close_ignores_late_receipt_and_new_requests(transaction):
    owner, operation, replies, busy = transaction
    before = owner.settings
    operation.use(candidate())
    operation.close()
    operation.close()
    owner.runtime.reply()
    operation.use(candidate("DEFAULT"))
    assert not operation.busy and len(owner.runtime.calls) == 1
    assert owner.avatar.mock_calls == [] and not replies
    assert owner.settings is before and owner.panel.settings is before
    assert busy == [True]


def test_close_during_rollback_does_not_touch_released_controls(transaction):
    owner, operation, replies, _ = transaction
    owner.avatar.set_image.side_effect = ValueError("合成试载失败")
    operation.use(candidate())
    owner.runtime.reply()
    operation.close()
    owner.panel = None
    owner.avatar = None
    owner.runtime.reply()
    assert not replies and not operation.busy


@pytest.mark.parametrize("kind", ["MOTION", "EXPRESSION", "UNKNOWN"])
def test_non_appearance_resources_cannot_be_used_as_avatars(transaction, kind):
    owner, operation, replies, busy = transaction
    operation.use(candidate(kind))
    assert not owner.runtime.calls and owner.avatar.mock_calls == []
    assert replies[0][0] is None and "预览" in replies[0][1]
    assert not busy


def test_dispatch_failure_releases_busy_without_changing_avatar(transaction):
    owner, operation, replies, busy = transaction
    owner.runtime.persist_platform = Mock(side_effect=RuntimeError("合成调度失败"))
    operation.use(candidate())
    assert owner.avatar.mock_calls == []
    assert replies[0][0] is None and "保存失败" in replies[0][1]
    assert not operation.busy and busy == [True, False]
