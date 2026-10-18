"""原生聊天协议类型及完整性验证；正文始终保留模型原文。"""

import json
from dataclasses import dataclass, field
from typing import Literal, NotRequired, TypedDict

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type ToolChoice = Literal['auto', 'none', 'required']


class TextPart(TypedDict):
    type: Literal['text']
    text: str


class ImageUrl(TypedDict):
    url: str


class ImagePart(TypedDict):
    type: Literal['image_url']
    image_url: ImageUrl


type Content = str | list[TextPart | ImagePart]


class FunctionCall(TypedDict):
    name: str
    arguments: str


class NativeToolCall(TypedDict):
    id: str
    type: Literal['function']
    function: FunctionCall


class TextMessage(TypedDict):
    role: Literal['system', 'user']
    content: Content


class AssistantMessage(TypedDict):
    role: Literal['assistant']
    content: str
    tool_calls: NotRequired[list[NativeToolCall]]
    provider_metadata: NotRequired[dict[str, JsonValue]]


class ToolMessage(TypedDict):
    role: Literal['tool']
    content: Content
    tool_call_id: str


type Message = TextMessage | AssistantMessage | ToolMessage


class FunctionDefinition(TypedDict):
    name: str
    description: str
    parameters: dict[str, JsonValue]


class ToolDefinition(TypedDict):
    type: Literal['function']
    function: FunctionDefinition


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str

    def message(self) -> NativeToolCall:
        return {'id': self.id, 'type': 'function',
                'function': {'name': self.name, 'arguments': self.arguments}}


@dataclass(frozen=True)
class AssistantReply:
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = 'stop'
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    def message(self) -> AssistantMessage:
        message: AssistantMessage = {'role': 'assistant', 'content': self.content}
        if self.tool_calls:
            message['tool_calls'] = [call.message() for call in self.tool_calls]
        if self.metadata:
            # 原生签名与思考上下文属于对应提供方；由适配器确认作用域再发送。
            message['provider_metadata'] = self.metadata
        return message


def validate_reply(content, calls, finish_reason):
    """未完整终止、半截参数及不一致结束原因都不能进入执行层。"""
    if content is None:
        content = ''
    if not isinstance(content, str) or finish_reason not in ('stop', 'tool_calls'):
        raise ValueError('模型回复未完整结束')
    if not isinstance(calls, list):
        raise ValueError('工具调用列表无效')
    parsed = []
    for call in calls:
        if not isinstance(call, dict) or call.get('type') != 'function':
            raise ValueError('工具调用格式无效')
        identifier, function = call.get('id'), call.get('function')
        if not isinstance(identifier, str) or not identifier.strip() or not isinstance(function, dict):
            raise ValueError('工具调用缺少标识')
        name, arguments = function.get('name'), function.get('arguments')
        if not isinstance(name, str) or not name.strip() or not isinstance(arguments, str):
            raise ValueError('工具调用缺少参数')
        # 参数必须是完整对象；字段权限由对应工具执行器验证。
        if not isinstance(json.loads(arguments), dict):
            raise ValueError('工具参数必须为对象')
        parsed.append(ToolCall(identifier, name, arguments))
    if bool(parsed) != (finish_reason == 'tool_calls'):
        raise ValueError('工具调用与结束原因不一致')
    return AssistantReply(content, tuple(parsed), finish_reason)


def parse_completion(payload):
    try:
        if not isinstance(payload, dict) or 'error' in payload:
            raise ValueError('无效响应')
        choices = payload['choices']
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError('无效候选数量')
        choice = choices[0]
        message = choice['message']
        return validate_reply(message.get('content'), message.get('tool_calls', []), choice.get('finish_reason'))
    except (ValueError, TypeError, AttributeError, KeyError, IndexError) as exc:
        raise RuntimeError('本机模型响应无效或未完整结束，请重试。') from exc
