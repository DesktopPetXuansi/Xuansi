"""编译隔离启动器与假解释器，验证启动边界，不执行桌宠或安装商店包。"""

import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "installer/store/StoreLauncher.cs"
COMPILER = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"


def compile_program(output, *sources, main=None):
    if not COMPILER.is_file():
        pytest.skip("需要 Windows 自带的 .NET Framework C# 编译器")
    command = [str(COMPILER), "/nologo", "/codepage:65001", "/target:winexe", "/platform:x64", "/reference:System.Windows.Forms.dll",
               "/out:" + str(output), *map(str, sources)]
    if main:
        command.append("/main:" + main)
    result = subprocess.run(command, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def wait_for_file(path):
    deadline = time.monotonic() + 5
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert path.is_file(), "隔离子进程未留下预期回执"


@pytest.mark.parametrize("directory", ["payload", "商店载荷 with spaces"])
def test_launcher_uses_own_directory_and_child_continues_after_launcher_exit(tmp_path, directory):
    payload = tmp_path / directory
    (payload / "runtime/python").mkdir(parents=True)
    (payload / "scripts").mkdir()
    bootstrap = payload / "scripts/store_bootstrap.py"
    bootstrap.write_text("raise AssertionError('must not execute Python')", encoding="utf-8")
    fake_source = tmp_path / "FakePython.cs"
    fake_source.write_text(r'''
using System;
using System.IO;
using System.Threading;
internal static class FakePython {
    private static void Main(string[] args) {
        string receipt = Environment.GetEnvironmentVariable("XUANSI_LAUNCHER_TEST_RECEIPT");
        File.WriteAllLines(receipt + ".started", new string[] {
            String.Join("|", args), Environment.CurrentDirectory,
            Environment.GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE"),
            Environment.GetEnvironmentVariable("XUANSI_LAUNCHER_TEST_INHERITED")
        });
        DateTime deadline = DateTime.UtcNow.AddSeconds(10);
        while (!File.Exists(receipt + ".release") && DateTime.UtcNow < deadline) Thread.Sleep(20);
        File.WriteAllText(receipt + ".continued", "continued");
    }
}
''', encoding="utf-8")
    compile_program(payload / "runtime/python/pythonw.exe", fake_source)
    launcher = payload / "Xuansi.exe"
    compile_program(launcher, SOURCE)
    caller = tmp_path / "unrelated current directory"
    caller.mkdir()
    receipt = tmp_path / "receipt"
    environment = dict(os.environ, XUANSI_LAUNCHER_TEST_RECEIPT=str(receipt),
                       XUANSI_LAUNCHER_TEST_INHERITED="preserved", PYTHONDONTWRITEBYTECODE="0")
    try:
        result = subprocess.run([str(launcher)], cwd=caller, env=environment,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        assert result.returncode == 0
        wait_for_file(receipt.with_suffix(".started"))
        assert not receipt.with_suffix(".continued").exists()
        arguments, working, no_bytecode, inherited = receipt.with_suffix(".started").read_text(
            encoding="utf-8-sig").splitlines()
        assert arguments.split("|") == ["-B", "-X", "utf8", str(bootstrap)]
        assert Path(working) == payload
        assert no_bytecode == "1"
        assert inherited == "preserved"
        assert bootstrap.read_text(encoding="utf-8").startswith("raise AssertionError")
        assert not list(caller.iterdir())
    finally:
        receipt.with_suffix(".release").touch()
    wait_for_file(receipt.with_suffix(".continued"))


@pytest.mark.parametrize("failure", ["missing-python", "missing-bootstrap", "invalid-python"])
def test_launcher_failure_reports_safe_message_without_starting_python(tmp_path, failure):
    payload = tmp_path / "错误载荷 with spaces"
    (payload / "runtime/python").mkdir(parents=True)
    (payload / "scripts").mkdir()
    if failure != "missing-python":
        (payload / "runtime/python/pythonw.exe").write_bytes(b"not an executable")
    if failure != "missing-bootstrap":
        (payload / "scripts/store_bootstrap.py").write_text("", encoding="utf-8")
    harness = tmp_path / "LauncherProbe.cs"
    harness.write_text(r'''
using System;
using System.IO;
internal static class LauncherProbe {
    private static int Main(string[] args) {
        return StoreLauncher.Run(args[0], delegate(string message) { File.WriteAllText(args[1], message); });
    }
}
''', encoding="utf-8")
    probe = tmp_path / "Probe.exe"
    compile_program(probe, SOURCE, harness, main="LauncherProbe")
    message = tmp_path / "error.txt"
    result = subprocess.run([str(probe), str(payload), str(message)], capture_output=True, timeout=5)
    assert result.returncode == 1
    content = message.read_text(encoding="utf-8-sig")
    assert "玄司" in content
    assert str(payload) not in content
    assert "Traceback" not in content
    assert set(path.name for path in tmp_path.iterdir()) <= {
        payload.name, harness.name, probe.name, message.name,
    }
