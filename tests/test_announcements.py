import asyncio
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from PySide6.QtWidgets import QApplication, QWidget

from pet.announcement_ui import AnnouncementController
from pet.announcements import AnnouncementCache, fetch_announcements


def published(revision, level="important"):
    return {
        "id": str(uuid4()), "revision": revision, "status": "published",
        "level": level, "title": "维护", "publishedAt": "2026-11-17T08:00:00Z",
        "body": [{"kind": "paragraph", "text": "维护说明"}],
    }


def change_page(items, more=False):
    return httpx.Response(200, json={"data": {"changes": items, "hasMore": more}}, headers={"ETag": '"page"'})


def test_first_sync_baselines_history_and_reminder_state_survives_restart(tmp_path):
    old, new, normal = published(1), published(2), published(3, "normal")
    cache = AnnouncementCache().apply(([old], 1, "", False)).apply(([new, normal], 3, "", False))
    assert not cache.entries[old["id"]]["read"]
    assert [item["id"] for item in cache.pending()] == [new["id"]]
    cache.mark([new["id"]], "reminded")
    path = tmp_path / "announcements.json"
    cache.save(path)
    loaded = AnnouncementCache.load(path)
    assert loaded.pending() == []
    assert not loaded.entries[new["id"]]["read"]
    assert not loaded.entries[normal["id"]]["read"]


def test_empty_baseline_allows_new_alert_and_later_withdrawal_clears_history():
    item = published(1)
    notice = {"id": item["id"], "revision": 2, "status": "withdrawn"}
    base = AnnouncementCache().apply(([], 0, '"empty"', False))
    cache = base.apply(([item], 1, "", False))
    assert [entry["id"] for entry in cache.pending()] == [item["id"]]
    assert cache.apply(([notice], 2, "", False)).entries == {}
    assert base.apply(([item, notice], 2, "", False)).pending() == []


def test_fetch_walks_pages_and_treats_304_as_only_matching_empty_page():
    item = published(4)
    notice = {"id": item["id"], "revision": 7, "status": "withdrawn"}
    calls = []

    def respond(request):
        calls.append(request.url.params["after"])
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        if calls[-1] == "3":
            assert request.headers["If-None-Match"] == '"last"'
            return change_page([item], more=True)
        if calls[-1] == "4":
            assert "If-None-Match" not in request.headers
            return change_page([notice])
        return httpx.Response(304)

    mock = httpx.MockTransport(respond)
    changes, revision, etag, reset = asyncio.run(fetch_announcements("https://example.test", 3, '"last"', transport=mock))
    assert changes[-1] == notice and revision == 7 and etag == "" and not reset
    assert asyncio.run(fetch_announcements("https://example.test", 7, '"empty"', transport=mock)) == (
        [], 7, '"empty"', False)
    assert calls == ["3", "4", "7"]


def test_future_cursor_recovers_by_replacing_cache():
    replacement = published(1)

    def respond(request):
        if request.url.params["after"] == "9":
            return httpx.Response(409, json={"error": {"code": "ANNOUNCEMENT_CURSOR_RESET"}})
        return change_page([replacement])

    old = published(9)
    cache = AnnouncementCache().apply(([old], 9, "", False))
    delta = asyncio.run(fetch_announcements("https://example.test", 9, "", transport=httpx.MockTransport(respond)))
    restored = cache.apply(delta)
    assert restored.revision == 1 and list(restored.entries) == [replacement["id"]]
    assert restored.pending() == []


def test_invalid_content_in_later_page_aborts_the_entire_sync():
    first = published(1)
    invalid = {**published(2), "body": [{"kind": "image", "text": "远程图片", "url": "https://example.test/image.png"}]}

    def respond(request):
        return change_page([first], more=True) if request.url.params["after"] == "0" else change_page([invalid])

    with pytest.raises(ValueError):
        asyncio.run(fetch_announcements("https://example.test", 0, "", transport=httpx.MockTransport(respond)))


def test_invalid_link_is_plain_text_and_does_not_block_sync():
    item = {**published(1), "body": [{"kind": "link", "text": "状态", "url": "https://[example.test]"}]}
    mock = httpx.MockTransport(lambda request: change_page([item]))
    changes, *_ = asyncio.run(fetch_announcements("https://example.test", 0, "", transport=mock))
    assert changes[0]["body"] == [{"kind": "paragraph", "text": "状态", "url": ""}]


def test_qt_defers_and_groups_alerts_until_eligible_then_removes_withdrawn_detail(tmp_path):
    app = QApplication.instance() or QApplication([])

    class Panel(QWidget):
        navigation = SimpleNamespace(set_announcement_unread=lambda unread: None)

        def mount_section(self, key, widget, on_open):
            widget.setParent(self)

    panel = Panel()
    avatar = QWidget()
    avatar.show()
    controller = AnnouncementController(SimpleNamespace(panel=panel, avatar=avatar), tmp_path / "cache.json",
                                        "https://example.test")
    controller.refresh = lambda: None
    opened = []
    panel.open_section = opened.append
    try:
        first, second = published(1), published(2)
        controller.cache = AnnouncementCache(initialized=True).apply(([first, second], 2, "", False))
        controller.remind(False)
        assert not controller.bubble.isVisible() and len(controller.cache.pending()) == 2
        controller.remind(True)
        assert controller.bubble.isVisible() and controller.bubble.label.text() == "有 2 条重要公告"
        assert controller.cache.pending() == []
        controller.bubble.open_button.click()
        assert opened == ["announcements"] and controller.page.selected == ""
        controller.remind(True)
        assert not controller.bubble.isVisible()

        third = published(3)
        controller._finish(([third], 3, "", False), "")
        controller.remind(True)
        controller.bubble.open_button.click()
        assert controller.page.selected == third["id"] and controller.cache.entries[third["id"]]["read"]
        withdrawal = {"id": third["id"], "revision": 4, "status": "withdrawn"}
        controller._finish(([withdrawal], 4, "", False), "")
        assert third["id"] not in controller.cache.entries
        assert controller.page.selected == "" and controller.page.article.toPlainText() == ""
    finally:
        controller.close()
        avatar.close()
        panel.close()
        app.processEvents()
