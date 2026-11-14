"""在后台进程执行首次资源准备；密钥只保存在系统凭据库。"""

import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal, Slot

from .ai.credentials import CredentialStore, ref_matches_endpoint
from .ai.install_plan import load_plan, save_plan
from .config import ROOT

LOG = logging.getLogger(__name__)


class StorePreparation(QObject):
    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, root, *, credential_store=None, worker=None, python=None, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        if not self.root.is_absolute():
            raise ValueError("数据目录必须是绝对路径。")
        self.store = credential_store if credential_store is not None else CredentialStore()
        self.worker = Path(worker) if worker is not None else ROOT / "scripts/store_prepare.py"
        self.python = str(python if python is not None else sys.executable)
        self.process = None
        self._files = ()
        self._new_reference = ""
        self._cancelled = False
        self._plan = None

    def start(self, plan, profile=None, key=""):
        """验证用户确认的选择后才写入草稿或启动下载。"""
        if self.process is not None:
            raise RuntimeError("资源准备已在进行。")
        plan.validate()
        if not plan.app_dir or Path(plan.app_dir).resolve() != self.root.resolve():
            raise ValueError("安装计划与数据目录不一致。")
        if key and profile is None:
            raise ValueError("缺少在线配置。")
        if profile is not None:
            profile.validate()
            if not profile.is_verified("text", "image", "tools", "stream", "cancel"):
                raise ValueError("在线配置尚未完成能力验证。")
            if (plan.provider_profile_id and plan.provider_profile_id != profile.fingerprint()
                    or plan.credential_ref and plan.credential_ref != profile.credential_ref):
                raise ValueError("安装计划与在线配置不一致。")
        if key and not ref_matches_endpoint(profile.credential_ref, profile.endpoint):
            raise ValueError("在线凭据与服务地址不一致。")

        data = self.root / "data"
        token = uuid4().hex
        request = data / f".store-request-{token}-plan.json"
        profile_path = data / f".store-request-{token}-profile.json"
        self._files = (request, request.with_suffix(".tmp"), profile_path)
        self._new_reference = ""
        self._cancelled = False
        self._plan = plan
        try:
            if key:
                # 不覆盖已有凭据；失败或取消时只清除本次独立新引用。
                if self.store.read(profile.credential_ref) is not None:
                    raise ValueError("在线凭据引用已存在，请重新输入密钥。")
                self.store.write(profile.credential_ref, key)
                self._new_reference = profile.credential_ref
            save_plan(plan, request)
            # 隔离解释器忽略 PYTHON* 环境变量；-B 防止子进程向只读载荷写字节码。
            arguments = ["-B", "-X", "utf8", str(self.worker), "--plan", str(request)]
            if profile is not None:
                profile_path.write_text(json.dumps(asdict(profile), ensure_ascii=False), encoding="utf-8")
                arguments += ["--profile", str(profile_path)]
            process = QProcess(self)
            environment = QProcessEnvironment.systemEnvironment()
            environment.insert("XUANSI_WRITABLE_ROOT", str(self.root))
            environment.insert("PYTHONUTF8", "1")
            environment.insert("PYTHONDONTWRITEBYTECODE", "1")
            environment.remove("XUANSI_API_KEY_DRAFT")
            process.setProcessEnvironment(environment)
            process.setWorkingDirectory(str(ROOT))
            # 绑定槽而非捕获 process/self 的闭包，避免延迟释放时形成对象循环。
            process.readyReadStandardOutput.connect(self._read_progress)
            process.readyReadStandardError.connect(self._read_progress)
            process.started.connect(self._process_started)
            process.finished.connect(self._process_finished)
            process.errorOccurred.connect(self._process_error)
            self.process = process
            process.start(self.python, arguments)
            if self.process is process:
                LOG.info("商店资源准备已启动")
        except Exception:
            self._cleanup(False)
            self.process = None
            raise

    def cancel(self):
        if self.process is not None:
            self._cancelled = True
            self.process.kill()
            LOG.info("已请求取消商店资源准备")

    @Slot()
    def _process_started(self):
        process = self.sender()
        if process is self.process and self._cancelled:
            process.kill()

    @Slot()
    def _read_progress(self):
        process = self.sender()
        if process is not self.process:
            return
        # 不透传子进程原始输出，避免异常文本或路径泄露到界面。
        process.readAllStandardOutput()
        process.readAllStandardError()
        self.progress.emit("正在准备已选择的资源，请保持网络连接。")

    @Slot(QProcess.ProcessError)
    def _process_error(self, error):
        process = self.sender()
        if process is self.process and error == QProcess.ProcessError.FailedToStart:
            self._finish(process, False, "准备程序无法启动，请重试。")

    @Slot(int, QProcess.ExitStatus)
    def _process_finished(self, code, status):
        process = self.sender()
        if process is not self.process:
            return
        success = not self._cancelled and status == QProcess.ExitStatus.NormalExit and code == 0
        if success:
            try:
                success = ((self.root / "data/settings.json").is_file()
                           and load_plan(self.root / "data/install-plan.json") == self._plan)
            except (OSError, ValueError, TypeError):
                success = False
        message = "准备完成。" if success else "已取消准备。" if self._cancelled else "准备未完成，请检查网络后重试。"
        self._finish(process, success, message)

    def _finish(self, process, success, message):
        self.process = None
        process.deleteLater()
        self._cleanup(success)
        LOG.info("商店资源准备结束 success=%s cancelled=%s", success, self._cancelled)
        self.finished.emit(success, message)

    def _cleanup(self, success):
        for path in self._files:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                LOG.warning("安装草稿清理未完成，类别=%s", type(exc).__name__)
        if self._new_reference and not success and not self._reference_in_use(self._new_reference):
            try:
                self.store.delete(self._new_reference)
            except (OSError, ValueError) as exc:
                LOG.warning("临时凭据清理未完成，类别=%s", type(exc).__name__)
        self._files = ()
        self._new_reference = ""

    def _reference_in_use(self, reference):
        """取消可能发生在设置提交后；不能删除已经被设置引用的凭据。"""
        try:
            raw = json.loads((self.root / "data/settings.json").read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return False
        except (OSError, ValueError) as exc:
            LOG.warning("无法核实设置引用，保留凭据，类别=%s", type(exc).__name__)
            return True
        if not isinstance(raw, dict):
            return True
        ai = raw.get("ai", {})
        if not isinstance(ai, dict):
            return True
        profile = ai.get("profile", {})
        if not isinstance(profile, dict):
            return True
        current = profile.get("credential_ref", "")
        return not isinstance(current, str) or current == reference
