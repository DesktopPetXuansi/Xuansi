"""Claude Messages 原生协议，保留原始 thinking/signature 内容块。"""

import copy
import json
from dataclasses import replace

from ...tool_protocol import validate_reply
from .base import HTTPProvider, ProviderError


def content_blocks(content):
    if isinstance(content, str):
        return [{'type': 'text', 'text': content}] if content else []
    blocks = []
    for part in content:
        if part['type'] == 'text':
            blocks.append(dict(part))
        else:
            url = part['image_url']['url']
            if not url.startswith('data:') or ';base64,' not in url:
                raise ProviderError('request', '图像必须使用内嵌 base64 资料。')
            header, data = url.split(';base64,', 1)
            blocks.append({'type': 'image', 'source': {'type': 'base64',
                           'media_type': header[5:], 'data': data}})
    return blocks


class ClaudeMessages(HTTPProvider):
    def headers(self):
        return {'x-api-key': self._key, 'anthropic-version': '2023-06-01'}

    def messages(self, messages):
        system, result = [], []
        for message in messages:
            role = message['role']
            if role == 'system':
                system.extend(content_blocks(message['content']))
                continue
            if role == 'tool':
                role = 'user'
                blocks = [{'type': 'tool_result', 'tool_use_id': message['tool_call_id'],
                           'content': content_blocks(message['content'])}]
            elif role == 'assistant':
                native = self.native(message).get('content')
                blocks = copy.deepcopy(native) if isinstance(native, list) else content_blocks(message['content'])
                if native is None:
                    blocks.extend({'type': 'tool_use', 'id': call['id'], 'name': call['function']['name'],
                                   'input': json.loads(call['function']['arguments'])}
                                  for call in message.get('tool_calls', []))
            else:
                blocks = content_blocks(message['content'])
            # 一批工具回执在同一 user 消息，tool_result 始终优先于新用户文字。
            if result and result[-1]['role'] == role:
                result[-1]['content'].extend(blocks)
            else:
                result.append({'role': role, 'content': blocks})
        return system, result

    def payload(self, messages, tools):
        system, converted = self.messages(messages)
        payload = {'model': self.profile.model, 'messages': converted}
        if system:
            payload['system'] = system
        if tools:
            payload['tools'] = [{'name': tool['function']['name'],
                                 'description': tool['function'].get('description', ''),
                                 'input_schema': tool['function']['parameters']} for tool in tools]
        return payload

    async def input_tokens(self, settings, messages, tools=()):
        data = await self.post(settings, 'messages/count_tokens', self.payload(messages, tools))
        value = data.get('input_tokens')
        if type(value) is not int or value < 0:
            raise ProviderError('protocol', '在线模型未返回有效容量。')
        # 官方计数为估计值，允许与实际调用有少量差异。
        return self.capacity_estimate(value)

    async def complete(self, settings, messages, tools=(), *, tool_choice='auto', stream=True,
                       json_mode=False, max_tokens=None):
        self.check_choice(tools, tool_choice)
        messages = await self.fit_messages(settings, messages, tools if tool_choice != 'none' else (),
                                           self.output_tokens(settings, max_tokens))
        payload = self.payload(messages, tools if tool_choice != 'none' else ())
        payload.update(max_tokens=self.output_tokens(settings, max_tokens), stream=stream)
        if tools and tool_choice != 'none':
            payload['tool_choice'] = {'type': 'any' if tool_choice == 'required' else 'auto'}
        # JSON输出约束由调用者的同一份提示提供，不能在计数后追加隐藏system指令。
        try:
            if stream:
                blocks, finish = await self.read_stream(settings, payload)
            else:
                data = await self.post(settings, 'messages', payload)
                blocks, finish = data['content'], data.get('stop_reason')
            calls = [{'id': block['id'], 'type': 'function', 'function': {
                'name': block['name'], 'arguments': json.dumps(block['input'], ensure_ascii=False)}}
                for block in blocks if block['type'] == 'tool_use']
            if finish not in ('end_turn', 'tool_use', 'stop_sequence'):
                raise ValueError('未完整结束')
            reason = 'tool_calls' if finish == 'tool_use' else 'stop'
            text = ''.join(block['text'] for block in blocks if block['type'] == 'text')
            reply = validate_reply(text, calls, reason)
            return self.check_reply(replace(reply, metadata=self.metadata({'content': blocks})), tools, tool_choice)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ProviderError('protocol', 'Claude 响应无效或未完整结束。') from None

    async def read_stream(self, settings, payload):
        blocks, fragments, closed, finish, stopped = {}, {}, set(), None, False
        async for event in self.events(settings, 'messages', payload):
            kind = event.get('type')
            if stopped:
                raise ValueError('结束后的事件')
            if kind == 'content_block_start':
                index = event['index']
                if type(index) is not int or index in blocks:
                    raise ValueError('重复内容块')
                blocks[index] = event['content_block']
            elif kind == 'content_block_delta':
                index, delta = event['index'], event['delta']
                block = blocks[index]
                if index in closed:
                    raise ValueError('关闭后的差量')
                field = {'text_delta': 'text', 'thinking_delta': 'thinking',
                         'signature_delta': 'signature'}.get(delta['type'])
                if field:
                    block[field] = block.get(field, '') + delta[field]
                elif delta['type'] == 'input_json_delta':
                    fragments[index] = fragments.get(index, '') + delta['partial_json']
            elif kind == 'content_block_stop':
                index = event['index']
                if index not in blocks or index in closed:
                    raise ValueError('内容块结束无效')
                closed.add(index)
                if index in fragments:
                    blocks[index]['input'] = json.loads(fragments[index])
            elif kind == 'message_delta':
                finish = event['delta'].get('stop_reason')
            elif kind == 'message_stop':
                stopped = True
        if not stopped or set(blocks) != closed or sorted(blocks) != list(range(len(blocks))):
            raise ValueError('缺少流式结束')
        return [blocks[index] for index in sorted(blocks)], finish
