"""同一台电脑上的模型资源采样，GPU 总量受其他应用影响，不冒充独占值。"""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.config import ROOT, Settings
from pet.inference import LocalEngine


async def gpu():
    process = await asyncio.create_subprocess_exec(
        "nvidia-smi",
        "--query-gpu=memory.used,utilization.gpu",
        "--format=csv,noheader,nounits",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    data, _ = await process.communicate()
    values = data.decode().strip().split(",")
    return {"total_used_mb": int(values[0]), "utilization_percent": int(values[1])}


async def main():
    engine = LocalEngine()
    report = {
        "gpu_before": await gpu(),
        "system_available_ram_gb": round(psutil.virtual_memory().available / 2**30, 2),
    }
    image = (ROOT / "data/verification/vision-fixture.png").read_bytes()
    samples = []

    async def watch():
        while True:
            if engine.process and engine.process.returncode is None:
                process = psutil.Process(engine.process.pid)
                cpu = process.cpu_times()
                samples.append(
                    {
                        "t": time.monotonic(),
                        "cpu": cpu.user + cpu.system,
                        "rss_mb": round(process.memory_info().rss / 2**20),
                    }
                )
            await asyncio.sleep(0.25)

    watcher = asyncio.create_task(watch())
    try:
        started = time.monotonic()
        await engine.chat(Settings(), "红圈附近是什么按钮？只回答名称。", [image], [])
        report["image_seconds_including_load"] = round(time.monotonic() - started, 2)
        report["gpu_after_image"] = await gpu()
        process = psutil.Process(engine.process.pid)
        report["model_priority"] = process.nice().name
        connections = [*psutil.Process().net_connections(kind="inet"), *process.net_connections(kind="inet")]
        report["non_loopback_connections"] = [
            str(c.raddr) for c in connections if c.raddr and c.raddr.ip not in ("127.0.0.1", "::1")
        ]
        report["listen_addresses"] = [
            c.laddr.ip for c in process.net_connections(kind="inet") if c.status == psutil.CONN_LISTEN
        ]
        started = time.monotonic()
        await engine.chat(Settings(), "鼠标附近的按钮叫什么？只回答名字。", [image], [])
        report["warm_image_seconds"] = round(time.monotonic() - started, 2)
        report["model_peak_sampled_rss_mb"] = max(s["rss_mb"] for s in samples)
        report["model_average_cpu_one_core_percent"] = round(
            (samples[-1]["cpu"] - samples[0]["cpu"]) / (samples[-1]["t"] - samples[0]["t"]) * 100, 2
        )
        pid = engine.process.pid
        await engine.stop()
        await asyncio.sleep(0.5)
        report["model_process_released"] = not psutil.pid_exists(pid)
        report["gpu_after_stop"] = await gpu()
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass
        await engine.stop()
    (ROOT / "data/verification/resources-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
