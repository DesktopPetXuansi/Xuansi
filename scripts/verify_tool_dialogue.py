"""真实本机原生工具对话验收；只使用合成截图、临时记忆和模拟动作回执。

依次运行各案例，不调用麦克风和扬声器。报告中的失败不会跳过或转为通过。
"""

import argparse
import asyncio
import json
import logging
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tool_fixture import Case, cases_for, picture

from pet import model_tools
from pet.config import Settings
from pet.inference import LocalEngine
from pet.memory import MemoryStore
from pet.tool_dialogue import run_dialogue

LOG = logging.getLogger(__name__)
MUTATIONS = {"save_memory", "set_speech_enabled", "play_motion"}


def ensure_available():
    """不接管或终止其他会话的服务；GPU 验收必须由操作者顺序安排。"""
    running = [process.pid for process in psutil.process_iter(["name"])
               if "llama-server" in (process.info["name"] or "").lower()]
    if running:
        raise RuntimeError(f"检测到已有模型进程，未启动验收：{running}")


def safe_record(value):
    """报告保留全部正文/参数/收据，仅将合成图片载荷换成长度标记以控制文件大小。"""
    if isinstance(value, dict):
        return {key: (f"<synthetic-image-data:{len(item)} chars>"
                      if key == "url" and isinstance(item, str) and item.startswith("data:image/")
                      else safe_record(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_record(item) for item in value]
    return value


def decoded(message):
    content = message["content"]
    if isinstance(content, list):
        content = next((part["text"] for part in content if part.get("type") == "text"), "{}")
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        return {}


def score(case, item, runtime, final):
    """仅评分，不改写模型输出、工具决策或执行结果。"""
    calls = item["calls"]
    names = {call["name"] for call in calls}
    successful = {entry["name"] for entry in item["tool_results"] if decoded(entry["message"]).get("ok") is True}
    text = final.content or ""
    checks = {"no_runtime_error": "error" not in item}
    expected = case.expected
    if expected in {"direct", "literal"}:
        checks["no_tools"] = not calls
        checks["single_completion_request"] = item["completion_requests"] == 1
        checks["has_visible_reply"] = bool(text)
        if expected == "literal":
            checks["literal_visible_and_preserved"] = "无需回应" in text and text in item["visible_text"]
    elif expected in {"no_mutation", "comment", "silent"}:
        checks["no_mutation_calls"] = not (names & MUTATIONS)
        checks["no_mutation_effects"] = (not runtime.memory.read() and not item["motion_receipts"]
                                        and not item["speech_changes"])
        if expected == "silent":
            checks["silent_finish"] = "finish_observation" in successful and not item["visible_text"] and not text
        elif expected == "comment":
            checks["visible_comment"] = bool(text) and "finish_observation" not in names
            tokens = {
                "comment0": ("错误", "失败", "构建", "error", "build"),
                "comment1": ("电", "充", "battery", "power", "1%"),
                "comment2": ("磁盘", "空间", "存储", "disk", "space"),
                "comment3": ("休息", "小时", "起来", "透气", "活动", "break", "hour"),
                "comment4": ("备份", "失败", "backup", "failed"),
            }[case.image]
            checks["comment_matches_fixture"] = any(token in text.lower() for token in tokens)
    elif expected in {"speech_off", "speech_on"}:
        checks["speech_tool_success"] = "set_speech_enabled" in successful
        checks["actual_speech_state"] = runtime.speech_override is (expected == "speech_on")
    elif expected in {"tts_fast", "tts_natural"}:
        checks["selected_engine"] = final.selected_tts == expected.removeprefix("tts_")
        checks["has_reply"] = bool(text)
    elif expected == "memory_tail":
        checks["search_success"] = "search_memory" in successful
        checks["tail_fact_recalled"] = "蓝鲸七号" in text
    else:
        checks["expected_tool_success"] = expected in successful
        if expected == "save_memory":
            checks["actually_persisted"] = "乌龙茶" in MemoryStore(runtime.memory.path).read()
        elif expected == "select_tts_engine":
            checks["actual_selected_engine"] = final.selected_tts == "natural"
        elif expected == "capture_screen":
            checks["image_understood"] = "蓝" in text or "blue" in text.lower()
        elif expected == "search_memory":
            checks["memory_understood"] = "乌龙茶" in text
        elif expected == "set_speech_enabled":
            checks["actual_speech_state"] = runtime.speech_override is False
        elif expected == "finish_observation":
            checks["silent_finish"] = final.content is None and not item["visible_text"]
    checks["ordinary_history_not_polluted"] = case.kind != "observation" or not runtime.history
    return checks


class Verification:
    def __init__(self, engine, settings, report, output, temporary):
        self.engine, self.settings = engine, settings
        self.report, self.output, self.temporary = report, output, temporary
        self.active = None
        self.runtime = None
        self.synthetic_picture = picture("blue")
        self.original_complete = engine.complete
        self.original_capture = model_tools.capture_screen
        self.original_execute = model_tools.ToolContext.execute

    def flush(self):
        self.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output.with_suffix(self.output.suffix + ".tmp")
        temporary.write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.output)

    def runtime_for(self, case, number):
        if case.preserve_history and self.runtime is not None:
            return self.runtime
        memory = MemoryStore(self.temporary / f"memory-{number}.json")
        if case.seed_memory:
            memory.save(case.seed_memory)
        runtime = SimpleNamespace(epoch=1, engine=self.engine, memory=memory, history=[],
                                  speech_override=case.initial_speech, motion_actions=("blink",))
        def set_speech(enabled):
            runtime.speech_override = enabled
            self.active["speech_changes"].append(enabled)
        async def request_motion(epoch, action):
            # 只确认模拟器受理，不冒充实际 Live2D 运行或动作完成。
            receipt = {"status": "accepted", "fixture": "simulated-qt-receipt", "action": action}
            self.active["motion_receipts"].append(receipt)
            return receipt
        def emit(epoch, content, kind):
            if not self.active["visible_text"]:
                self.active["first_visible_text_seconds"] = round(time.monotonic() - self.active["started"], 3)
            self.active["visible_text"].append(content)
        runtime.set_speech_enabled = set_speech
        runtime.request_motion = request_motion
        runtime.should_speak = lambda settings, kind="chat": (
            runtime.speech_override and (kind != "observation" or settings.speak_observations))
        runtime.reply = SimpleNamespace(emit=emit)
        runtime.state = SimpleNamespace(emit=lambda *args: None)
        runtime.memory_loaded = SimpleNamespace(emit=lambda *args: None)
        return runtime

    def install(self):
        async def complete(*args, **kwargs):
            self.active["completion_requests"] += 1
            reply = await self.original_complete(*args, **kwargs)
            self.active["model_responses"].append(safe_record(reply.message()))
            self.active["calls"].extend(asdict(call) for call in reply.tool_calls)
            return reply
        original_execute = self.original_execute
        async def execute(context, call):
            # 旁观生产执行器的真实结果，尤其记录观察独占结束后不会再送模型的收据。
            message = await original_execute(context, call)
            self.active["tool_results"].append({"name": call.name, "message": safe_record(message)})
            return message
        self.engine.complete = complete
        model_tools.capture_screen = lambda *args: self.synthetic_picture
        model_tools.ToolContext.execute = execute

    def restore(self):
        self.engine.complete = self.original_complete
        model_tools.capture_screen = self.original_capture
        model_tools.ToolContext.execute = self.original_execute

    async def run_case(self, case):
        number = len(self.report["checks"])
        item = {"case": case.label, "input": case.text, "expected": case.expected,
                "passed": False, "calls": [], "tool_results": [], "model_responses": [],
                "speech_changes": [], "motion_receipts": [], "visible_text": [],
                "first_visible_text_seconds": None, "completion_requests": 0,
                "started": time.monotonic()}
        self.active = item
        self.report["checks"].append(item)
        self.runtime = self.runtime_for(case, number)
        self.synthetic_picture = picture("blue")
        images = [picture(case.image)] if case.image else []
        settings = replace(self.settings, tts_engine=case.tts)
        LOG.info("开始工具验收 case=%s", case.label)
        try:
            final = await run_dialogue(self.runtime, self.runtime.epoch, settings, case.text,
                                       images, case.kind, (10, 20), None)
            item["answer"] = final.content
            item["selected_tts"] = final.selected_tts
            item["checks"] = score(case, item, self.runtime, final)
            item["passed"] = all(item["checks"].values())
        except Exception as exc:
            item["error"] = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            item["elapsed_seconds"] = round(time.monotonic() - item.pop("started"), 3)
            item["history"] = safe_record(self.runtime.history)
            item["persisted_memory"] = MemoryStore(self.runtime.memory.path).read()
            self.flush()
            LOG.info("工具验收结束 case=%s passed=%s elapsed=%.3f",
                     case.label, item["passed"], item["elapsed_seconds"])
        return item


async def verify(arguments, report):
    settings = replace(Settings(), gpu_layers=arguments.gpu_layers, observe=False)
    report["settings"] = {"temperature": settings.temperature, "top_p": settings.top_p,
                          "max_tokens": settings.max_tokens, "context_size": settings.context_size,
                          "gpu_layers": settings.gpu_layers}
    engine = LocalEngine()
    with tempfile.TemporaryDirectory(prefix="native-tool-verification-") as folder:
        runner = Verification(engine, settings, report, arguments.output, Path(folder))
        try:
            runner.install()
            await engine.start(settings)
            for case in cases_for(arguments.suite):
                await runner.run_case(case)
            if arguments.suite == "full":
                await runner.run_case(Case("performance/warmup", "你好。", "direct"))
                measurements = []
                for index in range(10):
                    measurements.append(await runner.run_case(
                        Case(f"performance/plain/{index + 1}", "你好，简单陪我聊一句。", "direct")))
                report["performance"] = {
                    "rounds": 10,
                    "completion_requests": [item["completion_requests"] for item in measurements],
                    "total_seconds": distribution([item["elapsed_seconds"] for item in measurements]),
                    "first_visible_text_seconds": distribution([
                        item["first_visible_text_seconds"] for item in measurements
                        if item["first_visible_text_seconds"] is not None]),
                    "first_audio_seconds": "未测：本脚本不合成或播放音频",
                    "before_after_comparison": "未测：需另行保存相同机器旧版本的独立基线",
                }
        finally:
            runner.restore()
            await engine.stop()
            runner.flush()


def distribution(values):
    return {"median": statistics.median(values), "min": min(values), "max": max(values)} if values else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("smoke", "full", "speech", "holdout"), default="smoke")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu-layers", type=int, default=99)
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    report = {"suite": arguments.suite, "checks": [], "passed": False,
              "fixtures": {"screen": "synthetic JPEG only", "memory": "temporary isolated files",
                           "motion": "simulated Qt accepted receipt; actual Live2D not tested",
                           "audio": "no microphone, synthesis or playback"},
              "measurement_notes": "首文字为生产reply.emit首次发布；完成请求数不含search_memory内部语义筛选。"
                                   "正文与工具结果原样记录，图片只保存合成载荷长度。"}
    try:
        ensure_available()
        asyncio.run(verify(arguments, report))
        report["passed"] = bool(report["checks"]) and all(item["passed"] for item in report["checks"])
    except Exception as exc:
        report["fatal_error"] = {"type": type(exc).__name__, "message": str(exc)}
    report["total"] = len(report["checks"])
    report["failures"] = sum(not item["passed"] for item in report["checks"])
    negatives = [item for item in report["checks"] if item["case"].startswith("negative/")]
    report["negative_cases"] = {"runs": len(negatives), "mutation_proposals": sum(
        bool({call["name"] for call in item["calls"]} & MUTATIONS) for item in negatives),
        "mutation_effects": sum(bool(item["persisted_memory"] or item["motion_receipts"] or item["speech_changes"])
                                for item in negatives)}
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "total": report["total"], "failures": report["failures"],
                      "output": str(arguments.output.resolve())}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
