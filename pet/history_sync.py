"""显式同意后同步新形象记录；每次先确认账号，网络失败不更改本机成功状态。"""

import asyncio
import logging

LOG = logging.getLogger(__name__)
HISTORY_SCOPES = {'resources:read', 'history:read', 'history:write'}


async def synchronize(store, client, *, cancelled=None):
    def stopped():
        return cancelled is not None and cancelled.is_set()

    if stopped():
        return 0
    state = await asyncio.to_thread(store.read)
    if not state['sync']['enabled'] or state['sync']['url'] != client.base_url:
        return 0
    profile = await client.request('GET', '/me')
    user = profile['id']
    count = 0
    for item in await asyncio.to_thread(store.pending, client.base_url, user):
        # 逐条重查开关和绑定，关闭/换账号后不继续发送之前取得的队列。
        pending = await asyncio.to_thread(store.pending, client.base_url, user)
        if stopped() or not any(current['id'] == item['id'] for current in pending):
            break
        await client.request('PUT', '/me/history/' + item['id'], store.payload(item))
        await asyncio.to_thread(store.mark_synced, item['id'], item['target'])
        count += 1
    LOG.info('形象历史同步完成 count=%d', count)
    return count
