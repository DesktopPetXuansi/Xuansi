"""通过真实 PKCE 和本机 HTTP 验证同步，凭据仅在内存，历史仅在临时目录。"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pet import platform_auth  # noqa: E402
from pet.appearance_import import AppearanceCandidate  # noqa: E402
from pet.history_sync import synchronize  # noqa: E402
from pet.personal_history import AppearanceHistory  # noqa: E402
from pet.platform_api import PlatformClient  # noqa: E402


class Tokens:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value

    def save(self, value):
        self.value = value

    def delete(self):
        self.value = None


async def verify(origin):
    assert urlsplit(origin).hostname in ('localhost', '127.0.0.1'), '验收仅允许本机网站'
    # 只把待打开的授权地址交给父测试进程，不打开用户浏览器或输出令牌。
    platform_auth.webbrowser.open = lambda uri: print('__QA_AUTHORIZE__' + uri, flush=True)
    tokens = await platform_auth.authorize(origin, history=True)
    assert {'resources:read', 'history:read', 'history:write'} <= set(tokens['scope'].split())
    client = PlatformClient(origin, store=Tokens(tokens))
    me = await client.request('GET', '/me')
    with tempfile.TemporaryDirectory(prefix='xuansi-history-qa-') as directory:
        history = AppearanceHistory(Path(directory) / 'history.json')
        history.record(AppearanceCandidate('DEFAULT', '此前本机记录'))
        assert not history.read()['sync']['enabled']
        history.bind(origin, me['id'])
        recorded = history.record(AppearanceCandidate('DEFAULT', '同步验收形象'))
        assert await synchronize(history, client) == 1
        assert await synchronize(history, client) == 0
        assert history.read()['entries'][0]['sync'] == 'synced'
        history.bind(origin, 'another-account')
        history.record(AppearanceCandidate('DEFAULT', '其他账号的本机记录'))
        assert await synchronize(history, client) == 0
        history.disable()
        assert await synchronize(history, client) == 0
        print('__QA_RESULT__' + json.dumps({'id': recorded['id'], 'synced': 1,
              'no_backfill': True, 'account_isolation': True, 'disabled_stops_uploads': True}), flush=True)


if __name__ == '__main__':
    try:
        asyncio.run(verify(json.loads(sys.stdin.readline())['origin']))
    except Exception as exc:
        print('客户端历史验收失败：' + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None
