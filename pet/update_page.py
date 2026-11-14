"""Native control-center surface for the signed Windows installer updater."""

import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import DATA, ROOT


def launcher_path():
    if ROOT.parent.name != "versions":
        return None
    launcher = ROOT.parents[1] / "Xuansi.exe"
    return launcher if launcher.is_file() and (launcher.parent / "update/update-state.json").is_file() else None


def read_preferences(path: Path):
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and all(type(raw.get(key)) is bool for key in ("autoCheck", "autoDownload", "installOnExit")):
            if not isinstance(raw.get("skipVersion", ""), str) or type(raw.get("remindAfter", 0)) not in (int, float):
                raise ValueError("invalid update reminder")
            raw.setdefault("skipVersion", "")
            raw.setdefault("remindAfter", 0)
            return raw
    except (OSError, ValueError):
        pass
    return {"autoCheck": True, "autoDownload": False, "installOnExit": False,
            "skipVersion": "", "remindAfter": 0}


def save_preferences(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def cached_bundle(launcher: Path, candidate):
    archive = launcher.parent / "update/downloads" / (candidate["sha256"] + ".zip")
    try:
        return archive.stat().st_size == candidate["bytes"]
    except OSError:
        return False


class UpdatePage(QWidget):
    install_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.launcher = launcher_path()
        self.preferences_path = DATA / "update-preferences.json"
        self.preferences = read_preferences(self.preferences_path)
        self.candidate = None
        self.downloaded = False
        self.installation_started = False
        self.operation = ""
        self.automatic = False
        self.process = QProcess(self)
        self.process.finished.connect(self._finished)
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(250)
        self.progress_timer.timeout.connect(self._progress)
        self.periodic = QTimer(self)
        self.periodic.setInterval(24 * 60 * 60 * 1000)
        self.periodic.timeout.connect(self._automatic_check)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        self.status = QLabel("当前版本：" + (ROOT / "VERSION").read_text(encoding="utf-8").strip())
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.details = QLabel("检查稳定渠道的新版本。")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        self.check_button = QPushButton("检查更新")
        self.check_button.clicked.connect(self.check)
        row.addWidget(self.check_button)
        self.download_button = QPushButton("下载更新")
        self.download_button.clicked.connect(self.download)
        self.download_button.hide()
        row.addWidget(self.download_button)
        self.cancel_button = QPushButton("取消下载")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.hide()
        row.addWidget(self.cancel_button)
        self.install_button = QPushButton("安装并重启")
        self.install_button.clicked.connect(self._confirm_install)
        self.install_button.hide()
        row.addWidget(self.install_button)
        self.remind_button = QPushButton("稍后提醒")
        self.remind_button.clicked.connect(self.remind_later)
        self.remind_button.hide()
        row.addWidget(self.remind_button)
        self.skip_button = QPushButton("跳过此版本")
        self.skip_button.clicked.connect(self.skip_version)
        self.skip_button.hide()
        row.addWidget(self.skip_button)
        row.addStretch()
        layout.addLayout(row)
        for key, label in (("autoCheck", "自动检查更新"), ("autoDownload", "自动下载更新"), ("installOnExit", "退出时安装已下载更新")):
            box = QCheckBox(label)
            box.setChecked(self.preferences[key])
            box.toggled.connect(lambda checked, key=key: self._set_preference(key, checked))
            layout.addWidget(box)
        layout.addStretch()
        if self.launcher is None:
            self.status.setText("当前不是支持内置更新的安装版")
            self.details.setText("源码运行版、商店版或旧安装版请使用各自的更新入口。")
            self.check_button.setEnabled(False)
        else:
            QTimer.singleShot(30000, self._automatic_check)
            if self.preferences["autoCheck"]:
                self.periodic.start()

    def _set_preference(self, key, checked):
        self.preferences[key] = checked
        if key == "autoCheck" and self.launcher is not None:
            if checked:
                self.periodic.start()
                self._automatic_check()
            else:
                self.periodic.stop()
        try:
            save_preferences(self.preferences_path, self.preferences)
        except OSError:
            self.details.setText("更新偏好保存失败，请检查数据目录。")

    def _run(self, operation, automatic=False):
        if self.launcher is None or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        self.operation = operation
        self.automatic = automatic
        self.check_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.process.start(str(self.launcher), ["--" + operation + "-update"])
        if operation == "download":
            self.status.setText("正在下载并验证更新…")
            self.cancel_button.show()
            self.remind_button.hide()
            self.skip_button.hide()
            self.progress.show()
            self.progress_timer.start()
        else:
            self.status.setText("正在检查更新…")

    def check(self):
        self._run("check")

    def _automatic_check(self):
        if self.preferences["autoCheck"] and time.time() >= self.preferences["remindAfter"]:
            self._run("check", automatic=True)

    def download(self):
        self._run("download")

    def cancel(self):
        if self.operation == "download" and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.status.setText("下载已取消；已保存的部分文件可在下次继续。")

    def _progress(self):
        if not self.candidate or self.launcher is None:
            return
        part = self.launcher.parent / "update/downloads" / (self.candidate["sha256"] + ".zip.part")
        try:
            self.progress.setValue(min(99, int(part.stat().st_size * 100 / self.candidate["bytes"])))
        except (OSError, ZeroDivisionError):
            pass

    def _finished(self, code, _status):
        operation = self.operation
        automatic = self.automatic
        self.operation = ""
        self.automatic = False
        self.progress_timer.stop()
        self.cancel_button.hide()
        self.check_button.setEnabled(True)
        self.download_button.setEnabled(True)
        if code != 0:
            if operation == "download" and self.status.text().startswith("下载已取消"):
                return
            self.status.setText("检查或下载失败")
            self.details.setText(self.process.readAllStandardError().data().decode("utf-8", errors="replace")[:300] or "请稍后重试。")
            return
        try:
            candidate = json.loads(self.process.readAllStandardOutput().data().decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self.status.setText("更新响应无法读取")
            return
        if candidate is None:
            self.status.setText("当前已是最新版本")
            self.download_button.hide()
            self.remind_button.hide()
            self.skip_button.hide()
            return
        if automatic and candidate["version"] == self.preferences["skipVersion"]:
            self._dismiss_candidate("版本 " + candidate["version"] + " 已跳过")
            return
        if self.candidate is None or self.candidate["sha256"] != candidate["sha256"]:
            self.downloaded = cached_bundle(self.launcher, candidate)
            self.install_button.hide()
        self.candidate = candidate
        self.status.setText("发现新版本 " + candidate["version"])
        self.details.setText("完整更新包 · " + f"{candidate['bytes'] / 1024**2:.1f} MiB")
        self.remind_button.show()
        self.skip_button.show()
        if operation == "download":
            self.downloaded = True
            self.progress.setValue(100)
            self.install_button.show()
            self.download_button.hide()
        else:
            self.install_button.setVisible(self.downloaded)
            self.download_button.setVisible(not self.downloaded)
            if self.preferences["autoDownload"] and not self.downloaded:
                self.download()

    def _dismiss_candidate(self, message):
        self.status.setText(message)
        self.downloaded = False
        self.download_button.hide()
        self.install_button.hide()
        self.remind_button.hide()
        self.skip_button.hide()

    def remind_later(self):
        self.preferences["remindAfter"] = time.time() + 24 * 60 * 60
        try:
            save_preferences(self.preferences_path, self.preferences)
        except OSError:
            self.details.setText("更新偏好保存失败，请检查数据目录。")
            return
        self._dismiss_candidate("已设为明天再提醒；仍可手动检查更新")

    def skip_version(self):
        if not self.candidate:
            return
        self.preferences["skipVersion"] = self.candidate["version"]
        try:
            save_preferences(self.preferences_path, self.preferences)
        except OSError:
            self.details.setText("更新偏好保存失败，请检查数据目录。")
            return
        self._dismiss_candidate("已跳过版本 " + self.candidate["version"] + "；手动检查仍可安装")

    def _confirm_install(self):
        if not self.downloaded:
            return
        if QMessageBox.question(self, "安装更新", "退出玄司、安装并重启新版本？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes:
            self.install_requested.emit()

    def launch_install(self):
        if self.installation_started or not self.downloaded or self.launcher is None:
            return False
        started, _pid = QProcess.startDetached(
            str(self.launcher), ["--apply-update", self.candidate["version"], self.candidate["sha256"]],
            str(self.launcher.parent),
        )
        self.installation_started = started
        return started
