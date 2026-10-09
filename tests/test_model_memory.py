"""模型检索必须扫描全部容量分片，并验证摘录来源与输出预算。"""

import json

import httpx
import pytest

from pet.config import Settings
from pet.model_memory import retrieve_memory


def mock_client(select, calls, token_scale=1, token_calls=None):
    async def handle(request):
        payload = json.loads(request.content)
        if request.url.path.endswith('/input_tokens'):
            if token_calls is not None:
                token_calls.append(payload)
            count = len(json.dumps(payload['messages'], ensure_ascii=False)) * token_scale
            return httpx.Response(200, json={'input_tokens': count})
        assert request.url.path == '/v1/chat/completions'
        assert payload['temperature'] == 0
        assert payload['chat_template_kwargs'] == {'enable_thinking': False}
        assert len(json.dumps(payload['messages'], ensure_ascii=False)) * token_scale + payload['max_tokens'] <= 4096
        candidates = json.loads(payload['messages'][-1]['content'])['candidates']
        calls.append(candidates)
        result = select(candidates)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': result}}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://localhost')


@pytest.mark.asyncio
async def test_late_relevant_excerpt_from_long_single_line():
    calls = []

    def select(candidates):
        selected = [{'id': c['id'], 'excerpt': '喜欢乌龙茶'} for c in candidates if '喜欢乌龙茶' in c['text']]
        return json.dumps({'selections': selected}, ensure_ascii=False)

    notes = '无关资料' * 1498 + '喜欢乌龙茶'
    async with mock_client(select, calls) as client:
        result = await retrieve_memory(client, Settings(), '喜欢什么茶', [notes])
    assert result == '喜欢乌龙茶'
    assert len(calls) > 1
    assert all(c['text'] in notes for batch in calls for c in batch)
    assert calls[-1][-1]['text'].endswith('喜欢乌龙茶')


@pytest.mark.asyncio
async def test_empty_model_selection_has_no_recency_fallback():
    async with mock_client(lambda _: '{"selections":[]}', []) as client:
        assert await retrieve_memory(client, Settings(), '茶', ['今天在跑步', '昨天看电影']) == ''


@pytest.mark.asyncio
@pytest.mark.parametrize('result', [
    '不是 JSON', '{"selections":[{"id":999,"excerpt":"资料"}]}',
    '{"selections":[{"id":0,"excerpt":"编造"}]}',
    '{"selections":[{"id":0,"excerpt":"资料"},{"id":0,"excerpt":"资料"}]}',
])
async def test_invalid_selection_fails_without_disclosing_memory(result):
    async with mock_client(lambda _: result, []) as client:
        with pytest.raises(RuntimeError, match='记忆') as error:
            await retrieve_memory(client, Settings(), '问题', ['私密资料'])
    assert '私密资料' not in str(error.value)


@pytest.mark.asyncio
async def test_many_short_lines_all_reach_model():
    calls, token_calls = [], []
    async with mock_client(lambda _: '{"selections":[]}', calls, token_calls=token_calls) as client:
        assert await retrieve_memory(client, Settings(), '问题', ['短记录'] * 1200) == ''
    assert sum(len(batch) for batch in calls) == 1200
    assert len(token_calls) < 100


@pytest.mark.asyncio
async def test_capacity_hint_adapts_after_long_record_then_short_records():
    calls, token_calls = [], []
    async with mock_client(lambda _: '{"selections":[]}', calls, token_scale=2, token_calls=token_calls) as client:
        assert await retrieve_memory(client, Settings(), '问题', ['甲' * 700, *(['短记录'] * 1200)]) == ''
    assert sum(c['text'] == '短记录' for batch in calls for c in batch) == 1200
    assert len(token_calls) < 100


@pytest.mark.asyncio
async def test_excess_selection_requires_final_model_screening():
    calls = []

    def select(candidates):
        # 第一层摘取每片的不同原文；第二层只选最末片，结果不靠程序截断。
        if all(len(c['text']) == 200 for c in candidates):
            chosen = candidates[-1:]
        else:
            chosen = candidates
        return json.dumps({'selections': [{'id': c['id'], 'excerpt': c['text'][-200:]} for c in chosen]}, ensure_ascii=False)

    async with mock_client(select, calls) as client:
        result = await retrieve_memory(client, Settings(), '问题', [str(i) * 700 for i in range(8)])
    assert len(result) <= 700
    assert any(all(len(c['text']) == 200 for c in batch) for batch in calls)


@pytest.mark.asyncio
async def test_relevant_fact_crossing_capacity_boundary():
    def select(candidates):
        return json.dumps({'selections': [
            {'id': c['id'], 'excerpt': '下周五参加设计会议'}
            for c in candidates if '下周五参加设计会议' in c['text']
        ]}, ensure_ascii=False)

    async with mock_client(select, []) as client:
        result = await retrieve_memory(client, Settings(), '何时开会', ['甲' * 696 + '下周五参加设计会议' + '乙' * 800])
    assert result == '下周五参加设计会议'


@pytest.mark.asyncio
async def test_token_heavy_fragment_is_split_by_actual_template_count():
    calls = []
    async with mock_client(lambda _: '{"selections":[]}', calls, token_scale=4) as client:
        assert await retrieve_memory(client, Settings(), '问题', ['甲' * 700]) == ''
    assert sum(len(batch) for batch in calls) > 1


@pytest.mark.asyncio
async def test_truncated_completion_is_rejected():
    async def handle(request):
        if request.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'input_tokens': 100})
        return httpx.Response(200, json={'choices': [{
            'finish_reason': 'length', 'message': {'content': '{"selections":[]}'},
        }]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://localhost') as client:
        with pytest.raises(RuntimeError, match='记忆'):
            await retrieve_memory(client, Settings(), '问题', ['资料'])


@pytest.mark.asyncio
async def test_output_including_newlines_cannot_exceed_limit():
    result = json.dumps({'selections': [{'id': 0, 'excerpt': '甲' * 350}, {'id': 1, 'excerpt': '乙' * 350}]})
    async with mock_client(lambda _: result, []) as client:
        with pytest.raises(RuntimeError, match='记忆'):
            await retrieve_memory(client, Settings(), '问题', ['甲' * 350, '乙' * 350])


@pytest.mark.asyncio
async def test_excessive_query_fails_before_completion():
    calls = []
    async with mock_client(lambda _: '{"selections":[]}', calls) as client:
        with pytest.raises(RuntimeError, match='容量'):
            await retrieve_memory(client, Settings(), '问题' * 3000, ['资料'])
    assert calls == []


@pytest.mark.asyncio
async def test_long_history_drops_oldest_complete_turns_and_keeps_recent_reference(caplog):
    history = [
        {'role': role, 'content': f'第{turn}轮' + '历史资料' * 130}
        for turn in range(3) for role in ('user', 'assistant')
    ]
    history[-2]['content'] = '我刚才问的是乌龙茶。' + '最近资料' * 100
    history[-1]['content'] = '接着问吧。' + '最近回复' * 100
    token_calls, model_calls = [], []

    async def handle(request):
        payload = json.loads(request.content)
        # 模拟服务端对完整聊天模板分词；调用预算必须包含模板与生成 token。
        count = len(json.dumps(payload['messages'], ensure_ascii=False))
        if request.url.path.endswith('/input_tokens'):
            token_calls.append(count)
            return httpx.Response(200, json={'input_tokens': count})
        assert count + payload['max_tokens'] <= 4096
        data = json.loads(payload['messages'][-1]['content'])
        model_calls.append(data)
        assert data['query'] == '那种茶我喜欢吗？'
        assert data['history'] == history[-2:]
        return httpx.Response(200, json={'choices': [{
            'finish_reason': 'stop', 'message': {'content': '{"selections":[{"id":0,"excerpt":"喜欢乌龙茶"}]}'},
        }]})

    with caplog.at_level('INFO', logger='pet.model_memory'):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://localhost') as client:
            assert await retrieve_memory(client, Settings(), '那种茶我喜欢吗？', ['喜欢乌龙茶'], history) == '喜欢乌龙茶'
    assert len(model_calls) == 1
    assert len(token_calls) <= 6
    assert history[0]['content'].startswith('第0轮')
    assert '乌龙茶' not in caplog.text


@pytest.mark.asyncio
async def test_long_current_query_uses_remaining_capacity_for_short_memory():
    calls, token_calls = [], []
    result = '{"selections":[{"id":0,"excerpt":"喜欢乌龙茶"}]}'
    async with mock_client(lambda _: result, calls, token_calls=token_calls) as client:
        assert await retrieve_memory(client, Settings(), '长问题' * 800, ['喜欢乌龙茶']) == '喜欢乌龙茶'
    assert len(calls) == 1
    assert len(token_calls) <= 3


@pytest.mark.asyncio
async def test_model_cannot_repeat_forever_without_reducing_selection():
    calls = []

    def select(candidates):
        return json.dumps({'selections': [
            {'id': c['id'], 'excerpt': c['text']} for c in candidates
        ]}, ensure_ascii=False)

    async with mock_client(select, calls, token_scale=2) as client:
        with pytest.raises(RuntimeError, match='收敛'):
            await retrieve_memory(client, Settings(), '问题', ['甲' * 350, '乙' * 350, '丙' * 350])
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_retrieval_logs_only_counts_not_private_material(caplog):
    result = '{"selections":[{"id":0,"excerpt":"私密内容"}]}'
    with caplog.at_level('INFO', logger='pet.model_memory'):
        async with mock_client(lambda _: result, []) as client:
            assert await retrieve_memory(client, Settings(), '私密问题', ['私密内容']) == '私密内容'
    assert '私密内容' not in caplog.text
    assert '私密问题' not in caplog.text
    assert 'selected=1' in caplog.text
