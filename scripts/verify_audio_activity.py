"""实机通知与开销验收：只输出数字零样本，不录音、不发出测试提示音。"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import comtypes
import numpy as np
import psutil
import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.config import ROOT
from pet.windows_audio import CoreAudioProbe


def main():
    if "--silent-child" in sys.argv:
        print(os.getpid(), flush=True)
        # 与真实桌宠相同的 PortAudio 输出路径；零样本不改变其他应用音量。
        sd.play(np.zeros(48000 * 2, dtype=np.float32), 48000)
        sd.wait()
        return
    samples = []
    finished = threading.Event()

    def watch():
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        probe = CoreAudioProbe()
        try:
            while not finished.is_set():
                present = probe.sample()
                pids = {
                    meter.pid for endpoint in probe.endpoints.values() for meter in endpoint.sessions.values()
                }
                samples.append((time.monotonic(), present, pids))
                finished.wait(0.1)
        finally:
            probe.close()
            probe = None
            comtypes.CoUninitialize()

    worker = threading.Thread(target=watch)
    worker.start()
    report = {}
    try:
        time.sleep(0.5)
        process = psutil.Process()
        before = process.cpu_times()
        started = time.monotonic()
        child = subprocess.Popen(
            [sys.executable, __file__, "--silent-child"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE,
        )
        child_output, _ = child.communicate(timeout=8)
        # venv 启动器另起解释器，音频会话归属实际解释器 PID。
        audio_pid = int(child_output.strip())
        report["new_process_session_observed"] = any(audio_pid in pids for _, _, pids in samples)
        start_self = time.monotonic()
        sd.play(np.zeros(48000, dtype=np.float32), 48000)
        sd.wait()
        report["own_output_session_observed"] = any(
            os.getpid() in pids for when, _, pids in samples if when > start_self
        )
        time.sleep(1)
        after = process.cpu_times()
        report["cpu_single_core_percent"] = round(
            (after.user + after.system - before.user - before.system) / (time.monotonic() - started) * 100, 2
        )
        report["sample_count"] = len(samples)
        report["external_audio_seen"] = any(present for _, present, _ in samples)
        report["note"] = "只验证零样本会话通知和实际接口；非零音量阻止与打断由自动逻辑测试验证。"
    finally:
        sd.stop()
        finished.set()
        worker.join(3)
        report["worker_stopped"] = not worker.is_alive()
    (ROOT / "data/verification/audio-session-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
