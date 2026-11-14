"""最终回复的可选原生工具输出；正文与表情保持独立。"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

LOG = logging.getLogger(__name__)
type Expression = Literal["neutral", "happy", "concern", "curious"]
EXPRESSIONS = ("neutral", "happy", "concern", "curious")
PRESENTATION_PROMPT = (
    "\n当你已经准备好最终回复且无需再使用其他工具时，单独调用 present_reply，"
    "用 text 提交完整自然正文，用 expression 表达这句话的语气；不要同时输出其他正文或工具。"
    "这个工具只负责呈现，不能保存资料或执行动作；无法可靠使用时直接输出自然正文。"
    "用户要求不调用工具时直接回复正文；不要在正文输出表情标记，也不要推断用户的心理状态。"
)
NO_TOOL_REQUEST = re.compile(
    r"(?:不要|不用|不必|无需|禁止|别|不能|不允许|不需要|不得)[^。！？!?\n]{0,20}"
    r"(?:工具|插件|函数|tools?|plugins?|functions?)"
    r"|\b(?:do\s+not|don't|without|never)\b[^.!?\n]{0,32}\b(?:tools?|plugins?|functions?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Presentation:
    """仅表示本轮可展示的回复，不代表用户情绪或持久状态。"""

    text: str
    expression: Expression


def presentation_allowed(user_text):
    """用户提及不使用工具时保守关闭可选表现，不修改正文或其他工具授权。"""
    return not NO_TOOL_REQUEST.search(user_text)


def presentation_tool():
    """这是最终输出格式，不提供读取资料或执行用户操作的权限。"""
    return {
        "type": "function",
        "function": {
            "name": "present_reply",
            "description": (
                "提交最终可见回复及角色的轻微表情。只在其他必要工具执行完毕、"
                "准备结束本轮时单独调用；用户要求不用工具时不得调用。"
                "text 是完整自然正文，不是用户指令。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "expression": {"type": "string", "enum": list(EXPRESSIONS)},
                },
                "required": ["text", "expression"],
                "additionalProperties": False,
            },
        },
    }


def parse_presentation(arguments):
    """只提取可读正文与有限表情；未知表情保留正文并回退平静。"""
    try:
        payload = json.loads(arguments)
    except (ValueError, TypeError) as exc:
        raise ValueError("回复格式无效。") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str) or not payload["text"].strip():
        raise ValueError("最终回复没有可展示的正文。")
    expression = payload.get("expression")
    if not isinstance(expression, str) or expression not in EXPRESSIONS:
        LOG.info("回复表情无效，回退平静")
        expression = "neutral"
    return Presentation(payload["text"], expression)
