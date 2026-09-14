"""解析本机 SSE，只交付可见正文；跨包推理标签保持隐藏。"""

import json


class VisibleText:
    def __init__(self):
        self.pending = ""
        self.thinking = False

    def feed(self, text):
        self.pending += text
        output = []
        while self.pending:
            marker = "</think>" if self.thinking else "<think>"
            index = self.pending.find(marker)
            if index >= 0:
                if not self.thinking:
                    output.append(self.pending[:index])
                self.pending = self.pending[index + len(marker) :]
                self.thinking = not self.thinking
                continue
            # 留住可能被下一包补全的标签前缀，正文不等待整句。
            keep = next(
                (size for size in range(len(marker) - 1, 0, -1) if self.pending.endswith(marker[:size])), 0
            )
            end = len(self.pending) - keep
            if not self.thinking:
                output.append(self.pending[:end])
            self.pending = self.pending[end:]
            break
        return "".join(output)


async def sse_events(response):
    parts = []
    size = 0
    async for line in response.aiter_lines():
        if not line:
            if parts:
                yield "\n".join(parts)
                parts, size = [], 0
        elif line.startswith("data:"):
            item = line[5:].removeprefix(" ")
            size += len(item)
            if size > 65536:
                raise RuntimeError("流式响应单条数据过大，请检查本机模型服务。")
            parts.append(item)
    if parts:
        yield "\n".join(parts)


async def read_completion(response, on_chunk):
    visible = VisibleText()
    result = ""
    finished = False
    async for data in sse_events(response):
        if data.strip() == "[DONE]":
            finished = True
            break
        try:
            payload = json.loads(data)
            if "error" in payload:
                raise ValueError("server error")
            choices = payload.get("choices", [])
            if not choices:
                continue  # usage 包没有正文。
            choice = choices[0]
            content = choice.get("delta", {}).get("content")
            if content is not None and not isinstance(content, str):
                raise ValueError("invalid content")
            finished = finished or choice.get("finish_reason") is not None
        except (ValueError, TypeError, AttributeError, KeyError, IndexError) as exc:
            # 不把服务端错误正文放到界面或日志，可能包含输入或私有路径。
            raise RuntimeError("本机流式响应无效，请重试或检查模型配置。") from exc
        text = visible.feed(content or "")[: max(0, 6000 - len(result))]
        if text:
            result += text
            await on_chunk(text)
    if not finished:
        raise RuntimeError("流式回复中断，已停止朗读，请重试。")
    return result.strip()
