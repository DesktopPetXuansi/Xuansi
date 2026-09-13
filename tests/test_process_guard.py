"""真实 Windows 子进程验证：只终止测试自身创建的等待进程。"""

import subprocess
import sys

from pet.process_guard import ProcessGuard


def test_closing_job_reaps_child():
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], creationflags=subprocess.CREATE_NO_WINDOW
    )
    guard = ProcessGuard()
    try:
        guard.attach(child.pid)
        guard.close()
        child.wait(timeout=3)
        assert child.returncode is not None
    finally:
        guard.close()
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=3)
