"""反馈只发送用户填写内容和明确勾选的版本信息，使用本机HTTP替身。"""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from pet.feedback import FeedbackDraft, collect_diagnostics
from pet.feedback_client import FeedbackClient


def draft(**changes):
    values = {"category": "BUG", "title": " 换形象失败 ", "description": " 点击使用后仍是原形象。 ", "contact": ""}
    values.update(changes)
    return FeedbackDraft(**values)


def test_payload_omits_unselected_diagnostics_and_empty_contact():
    payload = draft().payload()
    assert payload == {"category": "BUG", "title": "换形象失败", "description": "点击使用后仍是原形象。"}


@pytest.mark.parametrize("changes", [
    {"title": " "}, {"description": "\n"}, {"title": "字" * 81},
    {"description": "字" * 4001}, {"contact": "字" * 161}, {"category": "ADMIN"},
    {"description": "含有\0非法字符"}, {"diagnostics": {"apiKey": "不应发送"}},
])
def test_invalid_feedback_is_rejected_before_network(changes):
    with pytest.raises(ValueError):
        draft(**changes).payload()


def test_diagnostics_use_a_fixed_allowlist_without_user_or_machine_name(tmp_path, monkeypatch):
    import pet.feedback as feedback

    (tmp_path / "VERSION").write_text("0.8.0\n", encoding="utf-8")
    monkeypatch.setattr(feedback, "ROOT", tmp_path)
    monkeypatch.setattr(feedback.platform, "node", lambda: pytest.fail("不得采集设备名"))
    result = collect_diagnostics()
    assert set(result) == {"appVersion", "system", "architecture", "pythonVersion", "qtVersion"}
    assert result["appVersion"] == "0.8.0"
    assert all(isinstance(value, str) and 0 < len(value) <= 80 for value in result.values())


@pytest.mark.asyncio
async def test_submission_uses_csrf_cookie_and_origin_without_authorization():
    captured = []
    key = str(uuid4())

    async def reply(request):
        captured.append(request)
        if request.url.path.endswith("/auth/csrf"):
            return httpx.Response(200, json={"data": {"token": "synthetic-csrf"}},
                                  headers={"Set-Cookie": "xuansi_csrf=synthetic-csrf; Path=/"})
        assert request.method == "POST" and request.url.path == "/api/v1/feedback"
        assert request.headers["Origin"] == "http://localhost:3100"
        assert request.headers["X-CSRF-Token"] == "synthetic-csrf"
        assert request.headers["Idempotency-Key"] == key
        assert "xuansi_csrf=synthetic-csrf" in request.headers["Cookie"]
        assert "Authorization" not in request.headers
        assert json.loads(request.content) == draft().payload()
        return httpx.Response(201, json={"data": {
            "id": key, "createdAt": "2026-10-19T16:00:00Z", "status": "NEW",
        }})

    client = FeedbackClient("http://localhost:3100", transport=httpx.MockTransport(reply))
    receipt = await client.submit(draft().payload(), key)
    assert receipt.id == key and len(captured) == 2


@pytest.mark.asyncio
async def test_local_submission_is_not_forwarded_to_an_environment_proxy(monkeypatch):
    for variable in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(variable, "http://127.0.0.1:1")
    for variable in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(variable, "")
    key = str(uuid4())
    calls = []

    async def reply(reader, writer):
        # 使用真实回环连接，MockTransport不会覆盖HTTPX的代理选择。
        headers = (await reader.readuntil(b"\r\n\r\n")).decode("ascii")
        calls.append(headers.split("\r\n")[0])
        length = next((int(line.split(":", 1)[1]) for line in headers.split("\r\n")
                       if line.lower().startswith("content-length:")), 0)
        await reader.readexactly(length)
        data = ({"token": "csrf"} if headers.startswith("GET") else
                {"id": key, "status": "NEW", "createdAt": "2026-10-19T16:00:00Z"})
        body = json.dumps({"data": data}).encode()
        writer.write(f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(reply, "127.0.0.1", 0)
    async with server:
        base = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        receipt = await FeedbackClient(base).submit(draft().payload(), key)
    assert receipt.id == key and len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status, expected", [(404, "尚未"), (429, "频繁"), (500, "暂时"), (403, "校验")])
async def test_expected_server_errors_are_clear_without_exposing_response(status, expected):
    async def reply(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"token": "csrf"}})
        return httpx.Response(status, json={"error": {"message": "不应显示的私密内容"}})

    client = FeedbackClient("http://localhost:3100", transport=httpx.MockTransport(reply))
    with pytest.raises(ValueError, match=expected) as failure:
        await client.submit(draft().payload(), str(uuid4()))
    assert "私密内容" not in str(failure.value)


@pytest.mark.asyncio
async def test_success_without_a_matching_receipt_is_not_a_success():
    async def reply(request):
        return httpx.Response(200, json={"data": {"token": "csrf"}} if request.method == "GET" else
                              {"data": {"id": str(uuid4()), "status": "NEW", "createdAt": "invalid"}})

    client = FeedbackClient("http://localhost:3100", transport=httpx.MockTransport(reply))
    with pytest.raises(ValueError, match="确认"):
        await client.submit(draft().payload(), str(uuid4()))


@pytest.mark.parametrize("url", ["http://example.com", "https://user:password@example.com", "file:///tmp/report"])
def test_remote_unsafe_destinations_are_rejected(url):
    with pytest.raises(ValueError):
        FeedbackClient(url)
