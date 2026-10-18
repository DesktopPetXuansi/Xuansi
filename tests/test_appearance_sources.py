"""形象来源只通过既有后台队列工作，测试不访问真实资料或网络。"""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from pet.appearance_import import AppearanceCandidate
from pet.appearance_sources import AppearanceSources


class Platform(QObject):
    operation_completed = Signal(str, object)
    operation_failed = Signal(str, str)
    operation_finished = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.busy = False
        self.worker = None
        self.calls = []
        self.client = SimpleNamespace(request=AsyncMock(), install=AsyncMock())

    def api(self):
        return self.client

    def start(self, command, operation):
        if self.busy:
            return False
        self.busy = True
        self.worker = SimpleNamespace(cancel_requested=threading.Event())
        self.calls.append((command, operation))
        self.busy_changed.emit(True)
        return True

    def complete(self):
        command, operation = self.calls[-1]
        try:
            result = asyncio.run(operation())
        except asyncio.CancelledError:
            self.operation_failed.emit(command, "资源操作已取消")
        except Exception:
            self.operation_failed.emit(command, "资源操作失败")
        else:
            self.operation_completed.emit(command, result)
        self.finish(command)

    def finish(self, command):
        self.busy = False
        self.busy_changed.emit(False)
        self.worker = None
        self.operation_finished.emit(command)

    def cancel(self):
        if self.worker:
            self.worker.cancel_requested.set()


@pytest.fixture
def sources(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    platform = Platform()
    source = AppearanceSources(platform, image_directory=tmp_path / "images", resource_root=tmp_path / "resources")
    candidates, choices, errors, busy = [], [], [], []
    source.candidate_ready.connect(candidates.append)
    source.choices_ready.connect(lambda kind, values: choices.append((kind, values)))
    source.failed.connect(errors.append)
    source.busy_changed.connect(busy.append)
    yield source, platform, candidates, choices, errors, busy
    source.close()
    app.processEvents()


def test_local_import_yields_candidate_without_switching_avatar(sources, tmp_path):
    source, platform, candidates, _, errors, busy = sources
    path = tmp_path / "小猫.png"
    Image.new("RGBA", (8, 8), "red").save(path)
    source.local(path)
    assert not candidates and platform.calls[0][0].startswith("appearance-")
    platform.complete()
    assert candidates[0].name == "小猫" and candidates[0].kind == "IMAGE"
    assert (tmp_path / "images" / candidates[0].image_id).is_file()
    assert not errors and busy == [True, False]


def test_discover_is_public_only_and_filters_non_appearance_resources(sources):
    source, platform, _, choices, errors, _ = sources
    items = [{"id": kind, "kind": kind, "name": kind} for kind in (
        "MODEL", "IMAGE", "ANIMATION", "MOTION", "EXPRESSION")]
    platform.client.request.return_value = items
    source.discover()
    platform.complete()
    platform.client.request.assert_awaited_once_with("GET", "/resources?limit=100", anonymous=True)
    assert choices == [("discover", items[:3])] and not errors


def test_download_chooses_first_ready_and_preserves_resource_name(sources, monkeypatch, tmp_path):
    source, platform, candidates, _, errors, _ = sources
    platform.client.request.return_value = [
        {"id": "pending", "validationStatus": "PENDING"},
        {"id": "newest", "validationStatus": "READY"},
        {"id": "older", "validationStatus": "READY"}]
    calls = []
    def installed(version, **kwargs):
        calls.append((version, kwargs))
        return AppearanceCandidate("IMAGE", "entry", "a" * 64 + ".png")
    monkeypatch.setattr("pet.appearance_sources.installed_candidate", installed)
    source.download({"id": "resource", "kind": "IMAGE", "name": "官网小猫"})
    platform.complete()
    platform.client.request.assert_awaited_once_with("GET", "/resources/resource/versions")
    platform.client.install.assert_awaited_once_with("resource", "newest", root=tmp_path / "resources")
    assert calls[0][0] == "newest" and candidates[0].name == "官网小猫"
    assert not errors


def test_download_without_ready_version_is_readable(sources):
    source, platform, candidates, _, errors, _ = sources
    platform.client.request.return_value = [{"id": "pending", "validationStatus": "PENDING"}]
    source.download({"id": "resource", "kind": "MODEL", "name": "小猫"})
    platform.complete()
    assert not candidates and "可下载" in errors[0]
    platform.client.install.assert_not_awaited()


def test_mine_lists_default_installed_and_canonical_images_without_duplicates(sources, monkeypatch, tmp_path):
    source, platform, _, choices, errors, _ = sources
    directory = tmp_path / "images"
    directory.mkdir()
    image_id = "a" * 64 + ".png"
    Image.new("RGBA", (4, 4), "red").save(directory / image_id)
    Image.new("RGBA", (4, 4), "blue").save(directory / ("b" * 64 + ".png"))
    frames = [Image.new("RGBA", (4, 4), color) for color in ("red", "green")]
    frames[0].save(directory / ("c" * 64 + ".apng"), save_all=True, append_images=frames[1:], duration=100)
    (directory / "private.png").write_bytes(b"not canonical")
    monkeypatch.setattr("pet.appearance_sources.installed_resources", lambda root: [
        {"resourceVersionId": kind, "kind": kind} for kind in ("MODEL", "IMAGE", "MOTION", "EXPRESSION")])
    monkeypatch.setattr("pet.appearance_sources.installed_candidate", lambda version, **kwargs:
                        AppearanceCandidate(version, "已装小猫", image_id if version == "IMAGE" else ""))
    source.mine()
    platform.complete()
    assert not errors and choices[0][0] == "mine"
    values = choices[0][1]
    assert [item.kind for item in values] == ["DEFAULT", "MODEL", "IMAGE", "IMAGE", "ANIMATION"]
    assert len({item.image_id for item in values if item.image_id}) == 3
    assert all("a" * 64 not in item.name and "b" * 64 not in item.name for item in values)


def test_busy_cancel_and_close_never_emit_usable_candidate(sources, tmp_path):
    source, platform, candidates, _, errors, _ = sources
    source.local(tmp_path / "no-file.png")
    source.discover()
    assert len(platform.calls) == 1
    source.cancel()
    command = platform.calls[0][0]
    platform.operation_completed.emit(command, AppearanceCandidate("IMAGE", "取消的候选", "id"))
    platform.finish(command)
    assert not candidates
    source.installed("late")
    source.close()
    platform.operation_completed.emit("appearance-installed", AppearanceCandidate("MODEL", "迟到候选"))
    platform.operation_finished.emit("appearance-installed")
    assert not candidates
    source.discover()
    assert len(platform.calls) == 2 and not source.busy
    assert not errors or "取消" in errors[-1]


def test_completion_waits_for_worker_finished_before_emitting_candidate(sources):
    source, platform, candidates, _, _, _ = sources
    source.installed("version")
    selected = AppearanceCandidate("MODEL", "小猫")
    command = platform.calls[-1][0]
    platform.operation_completed.emit(command, selected)
    assert not candidates and source.busy
    platform.finish(command)
    assert candidates == [selected] and not source.busy


def test_foreign_task_receipts_are_ignored_and_invalid_kind_rejected(sources):
    source, platform, candidates, choices, errors, _ = sources
    source.download({"id": "motion", "kind": "MOTION", "name": "动作"})
    assert errors and not platform.calls
    platform.operation_completed.emit("remote", ["foreign"])
    platform.operation_finished.emit("remote")
    assert not candidates and not choices


def test_platform_cancel_after_completed_but_before_finished_discards_candidate(sources):
    source, platform, candidates, _, errors, _ = sources
    source.installed("version")
    command = platform.calls[-1][0]
    platform.operation_completed.emit(command, AppearanceCandidate("MODEL", "小猫"))
    platform.cancel()
    platform.finish(command)
    assert not candidates and not errors and not source.busy


def test_platform_error_is_emitted_only_after_task_retires(sources):
    source, platform, candidates, _, errors, _ = sources
    source.discover()
    platform.operation_failed.emit("appearance-discover", "官网暂时不可用")
    assert not errors and source.busy
    platform.finish("appearance-discover")
    assert errors == ["官网暂时不可用"] and not candidates and not source.busy


def test_busy_platform_rejects_sources_without_stealing_its_cancellation(sources):
    source, platform, candidates, _, errors, _ = sources
    platform.start("upload-existing", lambda: None)
    source.mine()
    source.cancel()
    assert len(platform.calls) == 1 and not platform.worker.cancel_requested.is_set()
    assert not candidates and not errors
    platform.finish("upload-existing")
    assert not source.busy


def test_default_directories_are_resolved_at_construction(monkeypatch, tmp_path):
    monkeypatch.setattr("pet.appearance_sources.appearance.DIRECTORY", tmp_path / "fresh-images")
    monkeypatch.setattr("pet.appearance_sources.platform_resources.RESOURCE_ROOT", tmp_path / "fresh-resources")
    source = AppearanceSources(Platform())
    assert source.image_directory == tmp_path / "fresh-images"
    assert source.resource_root == tmp_path / "fresh-resources"
    source.close()


def test_cancel_before_local_import_does_not_install_or_report_candidate(sources, tmp_path):
    source, platform, candidates, _, errors, busy = sources
    path = tmp_path / "小猫.png"
    Image.new("RGBA", (4, 4), "red").save(path)
    source.local(path)
    source.cancel()
    assert source.busy and busy == [True]
    platform.complete()
    assert not candidates and not errors and not source.busy
    assert not (tmp_path / "images").exists()
    assert busy == [True, False]
