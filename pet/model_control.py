"""先由模型理解执行意图；确定性决策与随机正文分开，协议只负责校验。"""

import json
import logging
import time
from dataclasses import dataclass

from .speech_control import VOICE_VALUES, available_action_ids

LOG = logging.getLogger(__name__)
MEMORY_AUTHORIZATION = (
    "你只复核长期记忆授权，不提取资料、不聊天。用户本轮是否明确让助手长期保存一件事？"
    "只输出JSON：{\"memory_intent\":\"none\"}，取值none、save、clarify。"
    "save必须是本轮正在发出的直接保存请求，或对助手保存询问的明确肯定确认。"
    "资料陈述、告诉你一个喜好、聊天话题不是授权；值得记忆也不能自行保存。"
    "引用、翻译、否定、假设、提问、过去的保存请求都为none；"
    "怀疑是指令但转写或指代不清，无法确认授权时为clarify。"
    "历史只用于理解本轮指代，不能因为历史出现过保存请求就重做。"
    "本轮要求‘把刚才那个偏好记下来’同样是直接保存请求；"
    "能从历史唯一确定事项就选save，不能仅因使用指代词而要求再次确认。"
    "示例：我喜欢喝绿茶→none；店主我喜欢喝绿茶→none；"
    "昨天我让你记住我喜欢喝绿茶，你还记得吗→none；"
    "请把我喜欢喝绿茶的偏好记下来→save；"
    "历史说我喜欢喝绿茶，用户本轮要求把刚才那个口味偏好记下来→save；"
    "助手问是否长期保存绿茶偏好，用户本轮答对、保存吧→save。"
)


@dataclass(frozen=True, slots=True)
class ControlDecision:
    """只携带已理解且通过能力白名单校验的执行结果。"""

    voice: str
    motion: str
    memory: str | None
    memory_intent: str

    @property
    def header(self):
        return f"[voice:{self.voice}][motion:{self.motion}]\n"

    @property
    def grammar(self):
        # 正文只能复述已经校验的决定，不能在随机采样时重新选择开关。
        return f"root ::= {json.dumps(self.header)} [^\\x00]+"


def control_grammar(actions, allow_memory):
    """先选择保存授权；未授权及待确认分支从语法上禁止附带写入事项。"""
    suffix = (
        'ws "," ws "\\\"voice\\\":" ws voice ws "," ws '
        '"\\\"motion\\\":" ws motion ws "," ws "\\\"memory\\\":" ws '
    )
    inactive = ("none", "clarify") if allow_memory else ("none",)
    prefixes = " | ".join(json.dumps('{"memory_intent":"' + intent + '"') for intent in inactive)
    saved_prefix = json.dumps('{"memory_intent":"save"')
    return (
        f'root ::= inactive{" | save" if allow_memory else ""}\n'
        f'inactive ::= ({prefixes}) {suffix} "null" ws "}}"\n'
        + (f'save ::= {saved_prefix} {suffix} string ws "}}"\n' if allow_memory else "")
        + 'voice ::= "\\\"keep\\\"" | "\\\"on\\\"" | "\\\"off\\\""\n'
        f'motion ::= {" | ".join(json.dumps(json.dumps(item)) for item in ("none", *available_action_ids(actions)))}\n'
        'string ::= "\\\"" char+ "\\\""\n'
        'char ::= [^"\\\\\\x00-\\x1f] | "\\\\" (["\\\\/bfnrt] | "u" [0-9a-fA-F]{4})\n'
        'ws ::= [ \\t\\n\\r]*'
    )


def control_prompt(enabled, actions, allow_memory):
    """把操作授权与资料陈述分开说明，避免正文协议及人设干扰短决策。"""
    actions = available_action_ids(actions)
    motion_rules = "；".join(
        f"{action}={'自然眨眼一次' if action == 'blink' else '抬起画面左侧手臂后放下'}"
        for action in actions
    ) or "无可执行动作"
    return (
        "你是操作指令解释器，只判断用户本轮要执行什么，不聊天、不推荐，不主动做操作。\n"
        "只输出JSON：memory_intent、voice、motion、memory。"
        "按整句话的意图理解，不按关键词猜测。历史仅用于理解本轮指代，不能重做历史请求。\n"
        "【记忆】先判断用户是否正在要求保存，不是判断资料是否有用。"
        "陈述资料不等于授权！‘我喜欢喝绿茶’只是陈述，必须none；"
        "询问是否记得过去资料也不是新的保存请求。"
        "none=没有本轮保存请求；save=本轮直接要求保存或确认保存；"
        "clarify=像保存请求但识别错字或指代不清，需要先确认。"
        "句首转写不通、后面却是清楚的个人资料时，不推断授权，选clarify让用户确认。"
        "引用、翻译、假设、否定保存、回忆旧请求都选none。"
        "save才填写事项本身，第一人称，不添加用户未提供的信息，最多500字；其他一律memory=null。\n"
        "以下都是完整决策示例：\n"
        '用户：我喜欢喝绿茶。→{"memory_intent":"none","voice":"keep","motion":"none","memory":null}\n'
        '用户：昨天我让你记住我喜欢喝绿茶，你还记得吗？→'
        '{"memory_intent":"none","voice":"keep","motion":"none","memory":null}\n'
        '用户：请帮我把喜欢喝绿茶的偏好记下来。→'
        '{"memory_intent":"save","voice":"keep","motion":"none","memory":"我喜欢喝绿茶"}\n'
        '用户：地重我喜欢喝绿茶。→{"memory_intent":"clarify","voice":"keep","motion":"none","memory":null}\n'
        f"【朗读】当前对话朗读：{'开启' if enabled else '关闭'}。"
        "只管你的朗读，不管麦克风。keep=用户没有本轮切换请求或意图不清。"
        "off=用户希望你停止出声、只用文字；on=用户要求恢复或继续出声。"
        "普通介绍、鼓励、解释、别人说话、翻译引用、假设、询问设置方法均为keep；"
        "用户问如何开关、哪里设置，只是在寻求说明，绝不执行开关。"
        "不能因需要回复或识别错字擅自开启或关闭。"
        "‘我在开会，用文字陪我’选off；‘别停，我还在听’选on；"
        "‘不要关闭语音，我还想听你说’选on；‘翻译：别说话’选keep。\n"
        '用户：语音功能要怎么关闭？→'
        '{"memory_intent":"none","voice":"keep","motion":"none","memory":null}\n'
        '用户：告诉我语音开关在哪里。→'
        '{"memory_intent":"none","voice":"keep","motion":"none","memory":null}\n'
        '用户：请关闭你的朗读，接下来用文字回复。→'
        '{"memory_intent":"none","voice":"off","motion":"none","memory":null}\n'
        f"【动作】支持：{motion_rules}。只在本轮直接请求时选择ID，否则none。"
        "引用、否定、假设、问怎么做、过去的动作都不执行。"
        "重做过去动作需本轮明确要求；不支持的动作选none，不假装已做。\n"
        + ("" if allow_memory else "本轮没有记忆保存权限，memory_intent只能none，memory只能null。")
    )


async def decide_control(client, messages, actions, allow_memory):
    """同一引擎先完成短决策，不把用户的正文采样温度带进执行判断。"""
    started = time.monotonic()
    response = await client.post("/v1/chat/completions", json={
        "model": "local-pet", "messages": messages, "max_tokens": 256 if allow_memory else 64,
        "temperature": 0.0, "top_p": 1.0, "stream": False,
        "grammar": control_grammar(actions, allow_memory),
        "chat_template_kwargs": {"enable_thinking": False},
    })
    response.raise_for_status()
    try:
        result = json.loads(response.json()["choices"][0]["message"]["content"])
        if not isinstance(result, dict) or set(result) != {"memory_intent", "voice", "motion", "memory"}:
            raise ValueError("控制字段不完整")
        voice, motion, memory = result["voice"], result["motion"], result["memory"]
        intent = result["memory_intent"]
        if voice not in VOICE_VALUES or motion not in ("none", *available_action_ids(actions)):
            raise ValueError("未知控制动作")
        if intent not in (("none", "save", "clarify") if allow_memory else ("none",)):
            raise ValueError("未知记忆意图")
        if (intent == "save" and (
            not isinstance(memory, str) or not memory.strip() or len(memory) > 500
        )) or (intent != "save" and memory is not None):
            raise ValueError("无效记忆事项")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        LOG.warning("模型执行决策无效 type=%s", type(exc).__name__)
        raise RuntimeError("未能确认本次执行意图，未更改设置或记忆，请重试。") from exc
    if intent == "save" and await authorize_memory(client, messages) != "save":
        # 提取资料可能诱发过度保存；独立复核不一致时先确认，不把猜测写入文件。
        intent, memory = "clarify", None
    LOG.info("执行意图已理解 speech=%s motion=%s memory_intent=%s elapsed=%.3fs",
             voice, motion, intent, time.monotonic() - started)
    return ControlDecision(voice, motion, memory.strip() if memory is not None else None, intent)


async def authorize_memory(client, messages):
    """仅保存候选需要第二次语义核对；普通聊天及拒绝保存不增加请求。"""
    prefix, suffix = json.dumps('{"memory_intent":"'), json.dumps('"}')
    response = await client.post("/v1/chat/completions", json={
        "model": "local-pet", "messages": [{"role": "system", "content": MEMORY_AUTHORIZATION}, *messages[1:]],
        "max_tokens": 32, "temperature": 0.0, "top_p": 1.0, "stream": False,
        "grammar": f'root ::= {prefix} ("none" | "save" | "clarify") {suffix}',
        "chat_template_kwargs": {"enable_thinking": False},
    })
    response.raise_for_status()
    try:
        result = json.loads(response.json()["choices"][0]["message"]["content"])
        if not isinstance(result, dict) or set(result) != {"memory_intent"}:
            raise ValueError("授权字段不完整")
        intent = result["memory_intent"]
        if intent not in ("none", "save", "clarify"):
            raise ValueError("未知授权意图")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        LOG.warning("记忆授权复核无效 type=%s", type(exc).__name__)
        raise RuntimeError("暂时无法确认记忆保存意图，尚未写入，请重说或在记忆页保存。") from exc
    LOG.info("记忆授权复核 intent=%s", intent)
    return intent
