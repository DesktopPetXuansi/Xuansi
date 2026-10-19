"""反馈的独立异步会话；只在用户点击后提交，不读取账号或模型凭据。"""

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import httpx

from .platform_auth import website_url

LOG = logging.getLogger(__name__)
STATUS_MESSAGES = {
    400: "请检查填写内容和长度后重试。", 403: "网站校验未通过，请检查官网连接后重试。",
    404: "当前网站尚未开通反馈接收，内容已保留，可先复制反馈内容。",
    409: "这条反馈的提交信息发生冲突，请修改内容后重试。",
    429: "提交过于频繁，请稍后重试。",
}


@dataclass(frozen=True)
class FeedbackReceipt:
    id: str
    created_at: str
    status: str


def response_data(response):
    if not response.is_success:
        LOG.warning("反馈请求未完成 status=%s", response.status_code)
        raise ValueError(STATUS_MESSAGES.get(response.status_code, "反馈服务暂时不可用，内容已保留，请稍后重试。"))
    try:
        if len(response.content) > 64 * 1024:
            raise ValueError("响应过大")
        data = response.json()["data"]
        if not isinstance(data, dict):
            raise ValueError("确认格式不符")
        return data
    except (KeyError, TypeError, ValueError):
        raise ValueError("网站返回的确认信息无法识别，内容已保留。") from None


def parse_receipt(data, key):
    """只有编号、状态和带时区的时间都匹配时，才能显示服务端确认。"""
    try:
        identifier, created_at, status = data.get("id"), data.get("createdAt"), data.get("status")
        if identifier != key or status not in ("NEW", "IN_PROGRESS", "RESOLVED") or not isinstance(created_at, str):
            raise ValueError
        if datetime.fromisoformat(created_at.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError
        return FeedbackReceipt(identifier, created_at, status)
    except (TypeError, ValueError):
        raise ValueError("网站返回的确认信息不完整，内容已保留。") from None


class FeedbackClient:
    def __init__(self, base_url, *, transport=None):
        self.base_url = website_url(base_url)
        self.transport = transport

    async def submit(self, payload, key):
        if str(UUID(key)) != key or not UUID(key).int:
            raise ValueError("反馈请求编号无效，请重新填写。")
        try:
            # 独立会话保留CSRF Cookie；沿用推理连接的直接访问规则，不读取环境代理或官网凭据。
            async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5), follow_redirects=False,
                                         trust_env=False, transport=self.transport) as client:
                csrf = response_data(await client.get(self.base_url + "/api/v1/auth/csrf"))
                token = csrf.get("token")
                if (not isinstance(token, str) or not token or len(token) > 512
                        or not token.isascii() or any(char.isspace() or ord(char) < 33 for char in token)):
                    raise ValueError("网站返回的确认信息不完整，请检查官网连接。")
                data = response_data(await client.post(self.base_url + "/api/v1/feedback", json=payload, headers={
                    "Origin": self.base_url, "X-CSRF-Token": token, "Idempotency-Key": key,
                }))
            receipt = parse_receipt(data, key)
            LOG.info("反馈已得到服务端确认 id=%s", receipt.id)
            return receipt
        except httpx.RequestError as exc:
            LOG.warning("反馈网络请求失败 type=%s", type(exc).__name__)
            raise ValueError("暂时无法连接反馈服务，内容已保留，请检查官网连接或稍后重试。") from None
