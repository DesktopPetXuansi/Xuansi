"""按明确协议选择适配器；不根据远端模型列表猜测能力。"""

from .base import ProviderError, TokenEstimate
from .claude import ClaudeMessages
from .gemini import GeminiNative
from .openai import OpenAICompatible


def create_provider(profile, *, key=None, transport=None, client=None):
    provider = {'claude': ClaudeMessages, 'gemini': GeminiNative}.get(profile.provider, OpenAICompatible)
    return provider(profile, key=key, transport=transport, client=client)


__all__ = ['create_provider', 'ProviderError', 'TokenEstimate']
