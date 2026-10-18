"""官方协议预置入口；声明能力不代表本项目已联网实测。"""

from .settings import ModelProfile

DOCUMENTED_AT = '2026-10-18'
SOURCES = {
    'openai': 'https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create',
    'bailian': 'https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions',
    'deepseek': 'https://api-docs.deepseek.com/guides/vision/',
    'kimi': 'https://platform.kimi.com/docs/api/chat',
    'zhipu': 'https://docs.bigmodel.cn/api-reference/模型-api/对话补全',
    'doubao': 'https://docs.volcengine.com/docs/ark/chat-api?lang=en',
    'claude': 'https://platform.claude.com/docs/en/api/python/messages/create',
    'gemini': 'https://ai.google.dev/api/generate-content',
}
MODEL_SOURCES = {
    'openai': 'https://developers.openai.com/api/docs/models/gpt-5.4',
    'bailian': 'https://help.aliyun.com/zh/model-studio/vision-model',
    'deepseek': 'https://api-docs.deepseek.com/guides/vision/',
    'kimi': 'https://platform.kimi.com/docs/api/chat',
    'zhipu': 'https://docs.bigmodel.cn/cn/guide/models/vlm/glm-4.6v',
    'doubao': 'https://docs.volcengine.com/docs/ark/model-list?lang=en',
    'claude': 'https://platform.claude.com/docs/en/models/sonnet-5-5/overview',
    'gemini': 'https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash',
}


def preset_profiles():
    """保留用户可编辑型号；未校验的声明不会自动成为完整回退候选。"""
    caps = ('text', 'image', 'tools', 'stream', 'cancel')
    entries = (
        ('openai', 'global', 'https://api.openai.com/v1', 'gpt-5.4'),
        ('bailian', 'cn-beijing', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen3.5-plus'),
        ('bailian', 'singapore', 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1', 'qwen3.5-plus'),
        ('deepseek', 'cn', 'https://api.deepseek.com', 'deepseek-flash'),
        ('kimi', 'cn', 'https://api.moonshot.cn/v1', 'kimi-k2.6'),
        ('zhipu', 'cn', 'https://open.bigmodel.cn/api/paas/v4', 'glm-4.6v'),
        ('doubao', 'cn-beijing', 'https://ark.cn-beijing.volces.com/api/v3', 'doubao-seed-2-0-lite-260428'),
        ('claude', 'global', 'https://api.anthropic.com/v1', 'claude-sonnet-5-5'),
        ('gemini', 'global', 'https://generativelanguage.googleapis.com/v1beta', 'gemini-2.5-flash'),
    )
    # 官方窗口均至少128k；首次只启用64k应用预算，为估算计数和图片保留余量。
    return tuple(ModelProfile(provider=provider, region=region, endpoint=endpoint, model=model,
                              capabilities=caps, context_tokens=65536)
                 for provider, region, endpoint, model in entries)
