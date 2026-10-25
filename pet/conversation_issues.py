"""对话恢复提示：只接受客户端受控错误，不回显远端正文或任意异常。"""

from dataclasses import dataclass
from typing import Literal

from mss.exception import ScreenShotError

from .ai.providers.base import ProviderError


@dataclass(frozen=True)
class ConversationIssue:
    message: str
    action: Literal["model", "preferences", "chat"]
    action_label: str


def failure_issue(error, kind):
    if isinstance(error, ScreenShotError):
        return ConversationIssue(
            "当前桌面暂不可读取。请解锁或唤醒屏幕，或取消附图后发送文字。", "chat", "返回文字对话",
        )
    if isinstance(error, ProviderError):
        # ProviderError 的消息由本机提供方适配器产生，禁止放入远端正文或请求 URL。
        next_step = {
            "authentication": "请检查 API Key、端点及该模型的访问权限，然后保存设置。",
            "quota": "请到服务商检查账户额度与计费状态，或更换可用模型后保存。",
            "rate_limit": "请稍后再试；也可检查服务商请求限制或更换模型。",
            "network": "请检查网络与 API 端点，然后重新发送。",
            "timeout": "请检查网络与服务状态；先确认本轮操作结果，再决定是否重新发送。",
            "context": "请缩短输入或新开一次对话，并检查模型的上下文预算。",
            "resource": "请在模型设置检查安装资源、模型路径和可用内存；也可选择在线模型。",
            "unsupported": "请在模型设置选择兼容的模型或运行方式。",
            "unavailable": "请检查模型或服务状态，也可选择其他模型后保存。",
        }.get(error.category, "请检查模型配置与能力，再决定是否重新发送。")
        return ConversationIssue(f"{error} {next_step}", "model", "检查模型设置")
    if kind == "preview":
        return ConversationIssue(
            "试听未完成。请检查语音组件、朗读设置和系统输出设备后再次试听；文字聊天仍可使用。",
            "preferences", "检查语音设置",
        )
    # 工具链的受控提示按完整字符串匹配；不能用 RuntimeError 类型信任任意异常正文。
    controlled = {
        "模型重复使用了同一工具标识，本轮未执行。": "模型重复使用了同一工具标识，本批操作未执行。请检查本轮记录后再决定是否重新发送。",
        "当前模型没有生成回复，请重新发送这句话。": "当前模型没有生成有效文字。请检查模型配置后重新发送。",
        "模型在工具禁用后仍请求操作，本轮已停止。": "模型在工具禁用后仍请求操作，本轮已停止。请先检查已有操作结果，再决定是否重新发送。",
        "本轮模型与工具处理超时，已停止后续操作，请重试。": "本轮模型与工具处理超时，已停止后续操作。请先检查已有操作结果，再决定是否重新发送。",
        "语音识别模型尚未安装完成。": "语音识别模型尚未安装完成。可先输入文字，在模型设置补齐语音组件。",
        "本次输入、工具和当前调用结果合计太长，请缩短后重试。": "本次输入、工具和当前调用结果合计太长。请缩短输入，并先检查已有操作结果。",
    }
    message = controlled.get(str(error))
    if message:
        return ConversationIssue(message, "model", "检查模型设置")
    return ConversationIssue(
        "本轮请求未完成。请检查模型配置或服务状态；若包含工具操作，先确认已有结果再决定是否重新发送。",
        "model", "检查模型设置",
    )


def preview_issue(runtime, settings):
    if "tts" not in settings.ai.voice_components:
        return ConversationIssue("试听未播放：尚未启用语音合成组件。可先文字聊天，在模型设置补齐语音组件。",
                                 "model", "检查语音组件")
    if runtime.speech_override is False:
        return ConversationIssue("试听未播放：本次运行的朗读已临时关闭。请在对话页开启朗读后再次试听。",
                                 "chat", "返回对话开启朗读")
    if runtime.speech_override is None and not settings.speak_replies:
        return ConversationIssue("试听未播放：已保存的回复朗读偏好为关闭。请启用朗读后再次试听。",
                                 "preferences", "检查语音设置")
    if runtime.audio_activity.blocked:
        return ConversationIssue(
            f"试听未播放：声音回避正在阻止输出（{runtime.audio_activity.status}）。请等待安静后重试，或检查声音回避设置。",
            "preferences", "检查声音回避",
        )
    return None
