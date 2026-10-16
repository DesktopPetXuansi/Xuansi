"""解析原生 SSE 的正文与工具差量，仅完整响应可进入对话执行层。"""

import json

from .tool_protocol import validate_reply


async def sse_events(response):
    parts = []
    size = 0
    async for line in response.aiter_lines():
        if not line:
            if parts:
                yield '\n'.join(parts)
                parts, size = [], 0
        elif line.startswith('data:'):
            item = line[5:].removeprefix(' ')
            size += len(item)
            if size > 1048576:
                raise RuntimeError('流式响应单条数据过大，请检查本机模型服务。')
            parts.append(item)
    if parts:
        yield '\n'.join(parts)


async def read_completion(response):
    """按 index 拼接函数参数，禁止将传输终止标记当作完整生成。"""
    texts, calls = [], {}
    finish_reason = None
    try:
        async for data in sse_events(response):
            if data.strip() == '[DONE]':
                break
            payload = json.loads(data)
            if not isinstance(payload, dict) or 'error' in payload:
                raise ValueError('服务错误')
            choices = payload.get('choices', [])
            if not isinstance(choices, list):
                raise ValueError('无效候选')
            if not choices:
                continue  # usage 包不代表回复结束。
            if len(choices) != 1 or finish_reason is not None:
                raise ValueError('结束后的重复数据')
            choice = choices[0]
            delta = choice.get('delta', {})
            content = delta.get('content')
            if content is not None:
                if not isinstance(content, str):
                    raise ValueError('无效正文')
                texts.append(content)
            fragments = delta.get('tool_calls', [])
            if not isinstance(fragments, list):
                raise ValueError('无效工具差量')
            for fragment in fragments:
                index = fragment.get('index')
                if type(index) is not int or index < 0:
                    raise ValueError('无效工具编号')
                call = calls.setdefault(index, {'id': '', 'type': 'function',
                                               'function': {'name': '', 'arguments': ''}})
                if fragment.get('type', 'function') != 'function':
                    raise ValueError('无效工具类型')
                function = fragment.get('function', {})
                for target, source, field in ((call, fragment, 'id'),
                                               (call['function'], function, 'name'),
                                               (call['function'], function, 'arguments')):
                    value = source.get(field)
                    if value is not None:
                        if not isinstance(value, str):
                            raise ValueError('无效工具字段')
                        target[field] += value
            finish_reason = choice.get('finish_reason')
        if sorted(calls) != list(range(len(calls))):
            raise ValueError('工具差量编号不连续')
        return validate_reply(''.join(texts), [calls[index] for index in sorted(calls)], finish_reason)
    except (ValueError, TypeError, AttributeError, KeyError, IndexError) as exc:
        raise RuntimeError('本机流式响应无效或中断，请重试。') from exc
