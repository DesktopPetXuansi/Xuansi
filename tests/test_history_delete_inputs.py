"""删除接口使用临时历史文件，防止非法标识符被当作清空请求。"""

import pytest

from pet.history_storage import HistoryFile


@pytest.fixture
def history(tmp_path):
    store = HistoryFile(tmp_path / 'history.json')
    store.write({'schema': 1, 'entries': [{'id': 'a'}, {'id': 'b'}]})
    return store


@pytest.mark.parametrize('identifier', ['', '   ', 0, False, True, [], {}])
def test_invalid_identifier_raises_without_changing_history(history, identifier):
    original = history.path.read_bytes()
    with pytest.raises(ValueError, match='标识'):
        history.remove(identifier)
    assert history.path.read_bytes() == original


def test_none_explicitly_clears_all_records(history):
    history.remove(None)
    assert history.read()['entries'] == []


def test_valid_identifier_removes_only_matching_record(history):
    history.remove('a')
    assert history.read()['entries'] == [{'id': 'b'}]


def test_unknown_identifier_preserves_all_records(history):
    history.remove('missing')
    assert history.read()['entries'] == [{'id': 'a'}, {'id': 'b'}]


@pytest.mark.parametrize('identifier', [None, 'a'])
def test_delete_does_not_replace_corrupt_history(history, identifier):
    history.path.write_text('{broken', encoding='utf-8')
    with pytest.raises(ValueError, match='损坏'):
        history.remove(identifier)
    assert history.path.read_text(encoding='utf-8') == '{broken'


def test_invalid_identifier_does_not_create_missing_history(tmp_path):
    store = HistoryFile(tmp_path / 'missing.json')
    with pytest.raises(ValueError, match='标识'):
        store.remove('')
    assert not store.path.exists()
