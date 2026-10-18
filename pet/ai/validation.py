"""安装/设置的显式合成能力验证；不读取屏幕、记忆或用户对话。"""

import asyncio
import base64
import json
import logging
import struct
import zlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from ..tool_protocol import AssistantReply
from .providers import ProviderError, create_provider

LOG = logging.getLogger(__name__)
def synthetic_image():
    """标准库生成左右纯色 PNG；颜色答案只在本机断言，不泄漏到提示。"""
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    scanline = b'\0' + b'\xff\0\0' * 32 + b'\0\0\xff' * 32
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 64, 64, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(scanline * 64)) + chunk(b'IEND', b''))


IMAGE = synthetic_image()
CAPABILITIES = ('text', 'image', 'tools', 'stream', 'cancel')
TOOL = {'type': 'function', 'function': {'name': 'validation_echo',
        'description': '验证工具，没有任何外部副作用。输入值应为 pet-validation。',
        'parameters': {'type': 'object', 'properties': {'value': {'type': 'string'}},
                       'required': ['value'], 'additionalProperties': False}}}


async def validate_profile(profile, key=None, *, transport=None):
    """仅全步骤成功后返回新配置；调用会产生费用，界面须先说明，取消不证明云端停止计费。"""
    profile.validate()
    provider = create_provider(profile, key=key, transport=transport)
    settings = ValidationSettings(context_size=min(8192, profile.context_tokens))
    verified = []
    task = None

    async def check(name, messages, tools=(), stream=False):
        async with asyncio.timeout(30):
            reply = await provider.complete(settings, messages, tools, stream=stream, max_tokens=512)
        if not isinstance(reply, AssistantReply):
            raise ProviderError('validation', f'{name}验证未取得完整回复。')
        LOG.info('模型验证收到完整响应 step=%s', name)
        return reply

    try:
        reply = await check('text', [{'role': 'user', 'content': '仅回复 pet-validation。'}])
        if 'pet-validation' not in reply.content:
            raise ProviderError('validation', '文字验证未返回指定内容。')
        verified.append('text')
        image = 'data:image/png;base64,' + base64.b64encode(IMAGE).decode('ascii')
        reply = await check('image', [{'role': 'user', 'content': [
            {'type': 'text', 'text': '识别图中左右两个色块的颜色。仅返回JSON对象，left和right字段用英文颜色名称。'},
            {'type': 'image_url', 'image_url': {'url': image}}]}])
        try:
            content = reply.content.strip()
            lines = content.splitlines()
            # 接受完整的 JSON 代码块包装；不截取夹杂说明的正文，颜色与字段仍严格断言。
            if len(lines) >= 3 and lines[0] in ('```json', '```') and lines[-1] == '```':
                content = '\n'.join(lines[1:-1])
            colors = json.loads(content)
        except (ValueError, TypeError):
            colors = None
        if colors != {'left': 'red', 'right': 'blue'}:
            raise ProviderError('validation', '图片验证未正确识别合成色块。')
        verified.append('image')
        # 使用auto而非通发required，兼容不能强制工具的思考模式。
        messages = [{'role': 'user', 'content': '必须调用 validation_echo，value 为 pet-validation；等待工具结果。'}]
        reply = await check('tools', messages, [TOOL])
        if len(reply.tool_calls) != 1 or reply.tool_calls[0].name != 'validation_echo':
            raise ProviderError('validation', '工具验证未返回预期无副作用调用。')
        call = reply.tool_calls[0]
        if json.loads(call.arguments) != {'value': 'pet-validation'}:
            raise ProviderError('validation', '工具验证参数不符合合成用例。')
        messages.extend([reply.message(), {'role': 'tool', 'tool_call_id': call.id,
                        'content': '{"result":"receipt-ok，最终请回复 receipt-ok"}'}])
        reply = await check('tools', messages)
        if 'receipt-ok' not in reply.content or reply.tool_calls:
            raise ProviderError('validation', '工具回执续答验证未通过。')
        verified.append('tools')
        # 复用真实记忆分片与出处校验，仅提供固定合成候选，不读取用户持久记忆。
        from ..model_memory import retrieve_memory
        try:
            async with asyncio.timeout(30):
                memory = await retrieve_memory(None, settings, '用户喝咖啡吗？',
                    ['用户不喝咖啡', '朋友小林喜欢咖啡', '桌宠玄司喜欢茶'],
                    limit=96, provider=provider)
        except ProviderError:
            raise
        except (RuntimeError, ValueError, TimeoutError):
            raise ProviderError('validation', '合成记忆验证未能确认原文、人物及否定关系。') from None
        if memory != '用户不喝咖啡':
            raise ProviderError('validation', '合成记忆验证混淆人物或丢失否定关系。')
        LOG.info('模型语义验证完成 capability=memory_relationship')
        reply = await check('negative_intent', [
            {'role': 'system', 'content': '工具只在用户明确要求实际执行时使用；赞美、评价和假设讨论只需聊天。'},
            {'role': 'user', 'content': '你刚才的动画真好看。'}], [TOOL])
        if reply.tool_calls or not reply.content.strip():
            raise ProviderError('validation', '负向意图验证未通过：普通赞美不能触发工具。')
        reply = await check('stream', [{'role': 'user', 'content': '仅回复 stream-ok。'}], stream=True)
        if 'stream-ok' not in reply.content:
            raise ProviderError('validation', '流式完整结束验证未通过。')
        verified.append('stream')
        # 取消真实在途请求，仅证明本客户端及时终止等待，不能证明远端终止计算。
        provider.stream_started.clear()
        task = asyncio.create_task(provider.complete(settings, [{'role': 'user',
                   'content': '连续输出数字直到输出长度上限。'}], stream=True, max_tokens=512))
        started = asyncio.create_task(provider.stream_started.wait())
        try:
            async with asyncio.timeout(30):
                await asyncio.wait((task, started), return_when=asyncio.FIRST_COMPLETED)
        finally:
            started.cancel()
            await asyncio.gather(started, return_exceptions=True)
        if task.done():
            task.result()
            raise ProviderError('validation', '取消验证请求过早完成，请重新验证。')
        task.cancel()
        try:
            async with asyncio.timeout(3):
                await task
        except asyncio.CancelledError:
            verified.append('cancel')
        else:
            raise ProviderError('validation', '在线请求未响应取消。')
        return replace(profile, verified_capabilities=tuple(verified),
                       verified_at=datetime.now(UTC).isoformat(),
                       verification_fingerprint=profile.fingerprint())
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await provider.stop()


@dataclass(frozen=True)
class ValidationSettings:
    """能力验证使用固定小预算，不继承用户对话与本地推理私有参数。"""
    max_tokens: int = 512
    temperature: float = 0.0
    top_p: float = 1.0
    context_size: int = 8192
