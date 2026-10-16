"""同机暖机对比新旧真实对话与TTS；只记录模拟播放接收时点，不启设备。"""

import argparse
import asyncio
import importlib
import json
import logging
import statistics
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import httpx
import psutil
import sounddevice as sd

LOG = logging.getLogger(__name__)


def summary(values):
    return {"median": statistics.median(values), "min": min(values), "max": max(values)} if values else None


def benchmark(arguments, report):
    root = arguments.project_root.resolve()
    sys.path.insert(0, str(root))
    package = importlib.import_module("pet")
    if not Path(package.__file__).resolve().is_relative_to(root):
        raise RuntimeError("pet导入来源与指定项目不一致，停止基准。")
    from PySide6.QtCore import Qt

    from pet.config import Settings
    from pet.memory import MemoryStore
    from pet.runtime import Runtime

    report["imported_pet"] = str(Path(package.__file__).resolve())
    active = None
    original_send, original_play, original_wait, original_stop = httpx.AsyncClient.send, sd.play, sd.wait, sd.stop

    async def send(client, request, *args, **kwargs):
        if active is not None and request.url.path == "/v1/chat/completions":
            active["generation_requests"] += 1
        return await original_send(client, request, *args, **kwargs)

    def receive(samples, rate, *args, **kwargs):
        # 真实波形进入假接收器；不等待波形时长，因此总耗时不包含扬声器播放。
        if active is not None:
            if active["first_audio_seconds"] is None:
                active["first_audio_seconds"] = round(time.monotonic() - active["started"], 4)
            active["clips"].append({"frames": len(samples), "sample_rate": rate})

    def reply(epoch, text, kind):
        if active is not None and text:
            if active["first_visible_text_seconds"] is None:
                active["first_visible_text_seconds"] = round(time.monotonic() - active["started"], 4)
            active["replies"].append(text)

    httpx.AsyncClient.send, sd.play = send, receive
    sd.wait, sd.stop = lambda *args, **kwargs: None, lambda *args, **kwargs: None
    runtime = None
    with tempfile.TemporaryDirectory(prefix="pet-dialogue-benchmark-") as folder:
        try:
            runtime = Runtime()
            runtime.memory = MemoryStore(Path(folder) / "memory.json")
            runtime.audio_activity.set_enabled(False)
            runtime.reply.connect(reply, Qt.ConnectionType.DirectConnection)
            runtime.failed.connect(lambda epoch, text: active["errors"].append(text) if active is not None else None,
                                   Qt.ConnectionType.DirectConnection)
            settings = Settings(observe=False, speak_replies=True, temperature=0.7, gpu_layers=99)
            if arguments.model_path:
                settings = replace(settings, model_path=str(arguments.model_path.resolve()))
            if arguments.projector_path:
                settings = replace(settings, projector_path=str(arguments.projector_path.resolve()))
            report["settings"] = {"temperature": settings.temperature, "gpu_layers": settings.gpu_layers,
                                  "tts_engine": settings.tts_engine, "max_tokens": settings.max_tokens}

            async def warmup():
                await runtime.engine.start(settings)
                await asyncio.to_thread(runtime.audio.synthesize, "你好", settings.speaker,
                                        settings.speed, settings.tts_engine)

            runtime.schedule(warmup()).result(timeout=180)
            # 资源暖机不触发旧控制分类。另行跑一轮真实链路，排除首请求/流水线初始化。
            async def turn():
                runtime.job = asyncio.current_task()
                runtime.history.clear()
                runtime.epoch += 1
                runtime.speech_override = None
                await runtime._conversation(runtime.epoch, settings, "你好，简单陪我聊一句。",
                                            "chat", None, None)

            runtime.schedule(turn()).result(timeout=180)
            for number in range(arguments.rounds):
                active = {"round": number + 1, "started": time.monotonic(), "generation_requests": 0,
                          "first_visible_text_seconds": None, "first_audio_seconds": None,
                          "clips": [], "replies": [], "errors": [], "reply_characters": 0, "passed": False}
                report["rounds"].append(active)
                try:
                    runtime.schedule(turn()).result(timeout=180)
                    active["reply_characters"] = sum(map(len, active["replies"]))
                    active["passed"] = bool(active["replies"] and active["clips"] and not active["errors"]
                                            and all(clip["frames"] > 0 for clip in active["clips"]))
                except Exception as exc:
                    active["errors"].append({"type": type(exc).__name__, "message": str(exc)})
                finally:
                    active["total_seconds"] = round(time.monotonic() - active.pop("started"), 4)
                    LOG.info("基准轮次结束 round=%d passed=%s", number + 1, active["passed"])
                    arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                active = None
        finally:
            if runtime is not None:
                try:
                    async def close():
                        await runtime._cancel()
                        await runtime.engine.stop()
                        await asyncio.to_thread(runtime.audio.unload)
                    runtime.schedule(close()).result(timeout=30)
                finally:
                    runtime.audio_activity.close()
                    runtime.loop.call_soon_threadsafe(runtime.loop.stop)
                    runtime.thread.join(timeout=10)
                    if runtime.thread.is_alive():
                        raise RuntimeError("本基准的后台线程未退出。")
                    runtime.loop.close()
            httpx.AsyncClient.send, sd.play, sd.wait, sd.stop = original_send, original_play, original_wait, original_stop
    report["summary"] = {field: summary([item[field] for item in report["rounds"] if item[field] is not None])
                         for field in ("generation_requests", "first_visible_text_seconds", "first_audio_seconds",
                                       "total_seconds", "reply_characters")}
    report["passed"] = len(report["rounds"]) == arguments.rounds and all(item["passed"] for item in report["rounds"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, help="仅本次基准使用的实验模型")
    parser.add_argument("--projector-path", type=Path, help="实验模型匹配的投影文件")
    arguments = parser.parse_args(argv)
    if arguments.rounds < 1:
        parser.error("--rounds必须至少为1")
    logging.basicConfig(level=logging.INFO)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"label": arguments.label, "project_root": str(arguments.project_root.resolve()),
              "rounds": [], "passed": False, "notes": "真实TTS生成；首音为假播放接收器收到首波形时点，"
              "不代表真实扬声器延迟。总耗时不含波形播放时长；记忆隔离，未启麦克风/屏幕采集。"}
    try:
        if any("llama-server" in (process.info["name"] or "").lower()
               for process in psutil.process_iter(["name"])):
            raise RuntimeError("已有模型服务运行，请先由所属会话结束，基准未启动。")
        benchmark(arguments, report)
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "output": str(arguments.output.resolve())}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
