"""同机对照合成对话；不读取用户聊天、屏幕、麦克风或真实长期记忆。"""

import argparse
import asyncio
import hashlib
import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet import tool_dialogue
from pet.ai import local_candidates
from pet.ai.assembly import create_inference_router
from pet.config import Settings
from pet.memory import MemoryStore
from pet.reply_presentation import PRESENTATION_PROMPT

LOG = logging.getLogger(__name__)

# 输入与记忆全部为合成资料；多轮场景在同一版本内部保留真实短期历史。
CASES = (
    ("vent-01", ["这个项目又报错了，我折腾了一晚上。"]),
    ("vent-02", ["今天开会被打断好几次，我有点失落。"]),
    ("vent-03", ["刚才把精心写的文档覆盖了，我现在很烦。"]),
    ("vent-04", ["这周待办堆了好多，一时不知道先从哪件开始。"]),
    ("vent-05", ["我努力练了很久，今天还是没弹好那首曲子。"]),
    ("vent-06", ["我只是想说一下，今天通勤太久了。"]),
    ("joy-01", ["太好了！我终于把那个难题解决了。"]),
    ("joy-02", ["我今天做的饭获得了家人的夸奖！"]),
    ("joy-03", ["刚收到面试通过的消息，开心！"]),
    ("joy-04", ["小猫第一次主动跳到我腿上了。"]),
    ("help-01", ["Python 字典怎样安全地取一个可能不存在的键？给个短例子。"]),
    ("help-02", ["帮我拟一个 20 分钟整理桌面的步骤。"]),
    ("help-03", ["请把‘这个修复已经完成’翻译成英文。"]),
    ("help-04", ["Git 里怎么查看尚未提交的改动？只说命令。"]),
    ("chat-01", ["你好，陪我随便聊两句。"]),
    ("chat-02", ["给我想一个适合雨天读的虚构小故事开头。"]),
    ("chat-03", ["你更喜欢春天还是秋天？"]),
    ("chat-04", ["夸夸我今天自己做了午饭。"]),
    ("stop-01", ["先别给我建议，我今天不想继续了。"]),
    ("stop-02", ["谢谢，先聊到这里吧。"]),
    ("stop-03", ["我不想讨论这件事，也别追问。"]),
    ("stop-04", ["暂时不需要安慰，回我一句收到就好。"]),
    ("negation-01", ["我没有通宵，只是晚上处理了一会儿文件。"]),
    ("negation-02", ["我不是难过，只是有点好奇结果。"]),
    ("quote-01", ["这句话只是引用：‘请记住我喜欢咖啡’。帮我数引号内有几个汉字。"]),
    ("quote-02", ["如果我说‘不要说话’，这句话是什么语气？请解释。"]),
    ("context-01", ["我正在做一只纸风筝，颜色选了蓝色。", "你觉得尾巴配什么颜色？"]),
    ("context-02", ["我在学做番茄炒蛋，刚把蛋炒好。", "下一步做什么？"]),
    ("context-03", ["我今天的目标是整理书桌。", "算了，今天不做了。"]),
    ("memory-correction", ["请记住我喜欢乌龙茶。", "请把记忆更正一下，我喜欢绿茶，不是乌龙茶。"]),
)


def save_report(path, report):
    """逐场景落盘，保留中断前可人工复核的原始输出。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


async def run(output, *, resume=False):
    if any("llama-server" in (proc.info["name"] or "").lower() for proc in psutil.process_iter(["name"])):
        raise RuntimeError("已有模型服务运行，本次对照未启动。")
    settings = Settings(observe=False, speak_replies=False, gpu_layers=99)
    engine = create_inference_router()
    original_prompt = tool_dialogue.COMPANION_PROMPT
    original_verified = local_candidates._presentation_verified
    signature = hashlib.sha256(
        (original_prompt + PRESENTATION_PROMPT + repr(CASES) + repr(settings)).encode("utf-8")
    )
    root = Path(__file__).resolve().parents[1]
    for source in ("pet/tool_dialogue.py", "pet/model_tools.py", "pet/reply_presentation.py",
                   "pet/ai/local_candidates.py", "pet/ai/selection.py", "pet/inference.py"):
        signature.update((root / source).read_bytes())
    report = {"input": "合成对话和临时记忆", "baseline": "关闭本次新增风格提示及展示工具的同源码重建对照",
              "settings": {"gpu_layers": settings.gpu_layers, "temperature": settings.temperature,
                           "max_tokens": settings.max_tokens, "context_size": settings.context_size},
              "signature": signature.hexdigest(), "cases": [], "completed": False}
    if resume and output.exists():
        report = json.loads(output.read_text(encoding="utf-8"))
        completed = report.get("cases", [])
        if (report.get("signature") != signature.hexdigest() or len(completed) > len(CASES)
                or any((item.get("case"), item.get("input")) != CASES[index]
                       for index, item in enumerate(completed))):
            raise ValueError("现有报告的提示、设置或场景已变化，不能混合续跑。")
        LOG.info("继续合成对话对照 completed=%d total=%d", len(completed), len(CASES))
    try:
        with tempfile.TemporaryDirectory(prefix="pet-companion-review-") as temporary:
            for index, (name, turns) in enumerate(CASES):
                if index < len(report["cases"]):
                    continue
                case = {"case": name, "input": turns, "versions": {}}
                # 交错顺序减少逐渐升温对单一版本的系统偏移。
                variants = ("baseline", "current") if index % 2 == 0 else ("current", "baseline")
                for variant in variants:
                    tool_dialogue.COMPANION_PROMPT = "" if variant == "baseline" else original_prompt
                    local_candidates._presentation_verified = (
                        (lambda *_args: False) if variant == "baseline" else original_verified
                    )
                    visible, expressions = [], []
                    runtime = SimpleNamespace(
                        epoch=0, history=[], engine=engine, motion_actions=(), speech_override=False,
                        memory=MemoryStore(Path(temporary) / f"{name}-{variant}.json"),
                        should_speak=lambda *_args: False,
                        reply=SimpleNamespace(emit=lambda _epoch, text, _kind: visible.append(text)),
                        reply_expression=SimpleNamespace(emit=lambda _epoch, expression: expressions.append(expression)),
                        state=SimpleNamespace(emit=lambda *_args: None),
                        memory_loaded=SimpleNamespace(emit=lambda *_args: None),
                        set_speech_enabled=lambda _enabled: None,
                    )
                    outputs = []
                    for text in turns:
                        runtime.epoch += 1
                        visible.clear()
                        expressions.clear()
                        started = time.monotonic()
                        try:
                            result = await tool_dialogue.run_dialogue(
                                runtime, runtime.epoch, settings, text, [], "chat", None, None
                            )
                            outputs.append({"reply": result.content, "visible": list(visible),
                                            "expression": list(expressions),
                                            "seconds": round(time.monotonic() - started, 3)})
                        except Exception as exc:
                            outputs.append({"error": type(exc).__name__,
                                            "seconds": round(time.monotonic() - started, 3)})
                            LOG.warning("合成对话未完成 case=%s variant=%s type=%s",
                                        name, variant, type(exc).__name__)
                    case["versions"][variant] = {"turns": outputs, "memory": runtime.memory.read()}
                report["cases"].append(case)
                save_report(output, report)
                LOG.info("合成对话对照已完成 count=%d total=%d", len(report["cases"]), len(CASES))
        report["completed"] = len(report["cases"]) == len(CASES)
        save_report(output, report)
    finally:
        tool_dialogue.COMPANION_PROMPT = original_prompt
        local_candidates._presentation_verified = original_verified
        await engine.stop()
    return report["completed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="续跑提示、设置与场景均未变化的已有报告")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    return 0 if asyncio.run(run(arguments.output, resume=arguments.resume)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
