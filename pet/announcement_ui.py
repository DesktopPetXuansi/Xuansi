"""原生公告页、可点击提醒与异步同步的生命周期。"""

import asyncio
import logging
import random
from concurrent.futures import CancelledError
from datetime import datetime
from html import escape

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .announcements import AnnouncementCache, fetch_announcements, https_link
from .avatar_bubble import PASSIVE

LOG = logging.getLogger(__name__)
USER_ROLE = Qt.ItemDataRole.UserRole
PAGE_SIZE = 20


class AnnouncementPage(QWidget):
    refresh_requested = Signal()
    opened = Signal(str)

    def __init__(self):
        super().__init__()
        self.offset = 0
        self.selected = ""
        self.cache = AnnouncementCache()
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.status = QLabel("正在等待公告同步")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        toolbar.addWidget(self.status, 1)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_requested)
        toolbar.addWidget(refresh)
        layout.addLayout(toolbar)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        listing = QWidget()
        rows = QVBoxLayout(listing)
        rows.setContentsMargins(0, 0, 0, 0)
        self.items = QListWidget()
        self.items.setAccessibleName("公告历史")
        self.items.setMinimumHeight(210)
        self.items.itemClicked.connect(self._open_item)
        self.items.itemActivated.connect(self._open_item)
        rows.addWidget(self.items)
        pagination = QHBoxLayout()
        self.previous = QPushButton("上一页")
        self.previous.clicked.connect(lambda: self._advance(-PAGE_SIZE))
        self.next = QPushButton("下一页")
        self.next.clicked.connect(lambda: self._advance(PAGE_SIZE))
        pagination.addWidget(self.previous)
        pagination.addWidget(self.next)
        pagination.addStretch()
        rows.addLayout(pagination)
        self.stack.addWidget(listing)

        detail = QWidget()
        content = QVBoxLayout(detail)
        content.setContentsMargins(0, 0, 0, 0)
        back = QPushButton("返回公告列表")
        back.clicked.connect(self.show_list)
        content.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        self.article = QTextBrowser()
        self.article.setAccessibleName("公告正文")
        self.article.setOpenLinks(False)
        self.article.anchorClicked.connect(self._open_link)
        self.article.setMinimumHeight(240)
        content.addWidget(self.article)
        self.stack.addWidget(detail)
        self.render(self.cache)

    def render(self, cache):
        self.cache = cache
        if self.selected and self.selected not in cache.entries:
            self.show_list()
            self.status.setText("这条公告已撤回")
        else:
            self._list_rows()

    def _advance(self, amount):
        self.offset += amount
        self._list_rows()

    def _list_rows(self):
        rows = sorted(self.cache.entries.values(), key=lambda item: item["revision"], reverse=True)
        last_page = max(0, len(rows) - 1) // PAGE_SIZE * PAGE_SIZE
        self.offset = min(max(0, self.offset), last_page)
        self.items.clear()
        for entry in rows[self.offset:self.offset + PAGE_SIZE]:
            labels = []
            if entry["level"] == "important":
                labels.append("重要")
            if not entry["read"]:
                labels.append("未读")
            labels.append(entry["title"])
            item = QListWidgetItem(" · ".join(labels))
            item.setToolTip(entry["title"].replace("<", "＜").replace(">", "＞"))
            item.setData(USER_ROLE, entry["id"])
            self.items.addItem(item)
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(self.offset < last_page)

    def _open_item(self, item):
        self.opened.emit(item.data(USER_ROLE))

    @staticmethod
    def _open_link(url: QUrl):
        if url.isValid() and https_link(url.toString()):
            QDesktopServices.openUrl(url)

    def show_list(self):
        self.selected = ""
        self.article.clear()
        self.stack.setCurrentIndex(0)
        self._list_rows()

    def show_article(self, entry):
        self.selected = entry["id"]
        timestamp = datetime.fromisoformat(entry["publishedAt"]).astimezone().strftime("%Y-%m-%d %H:%M")
        level = "重要公告" if entry["level"] == "important" else "普通公告"
        sections = [f"<h2>{escape(entry['title'])}</h2><p>{level} · {timestamp}</p>"]
        for block in entry["body"]:
            value = escape(block["text"])
            match block["kind"]:
                case "heading":
                    sections.append(f"<h3>{value}</h3>")
                case "strong":
                    sections.append(f"<p><strong>{value}</strong></p>")
                case "bullet":
                    sections.append(f"<ul><li>{value}</li></ul>")
                case "link":
                    target = escape(block["url"], quote=True)
                    sections.append(f'<p><a href="{target}">{value}</a></p>')
                case _:
                    sections.append(f"<p>{value}</p>")
        self.article.setHtml("".join(sections))
        self.stack.setCurrentIndex(1)


class AnnouncementBubble(QFrame):
    opened = Signal(str)

    def __init__(self):
        super().__init__(None, PASSIVE)
        self.setObjectName("announcementBubble")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(280)
        self.setStyleSheet("""
            QFrame#announcementBubble {background:#fffdf6; border:1px solid #ccd5c8; border-radius:10px;}
            QLabel {color:#344239;}
            QPushButton {color:#344239; background:#f4f0e7; padding:4px 10px; border:1px solid #ccd5c8;}
        """)
        box = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        box.addWidget(self.label)
        buttons = QHBoxLayout()
        self.open_button = QPushButton("查看")
        self.open_button.clicked.connect(self._open)
        buttons.addWidget(self.open_button)
        close = QPushButton("关闭")
        close.clicked.connect(self.hide)
        buttons.addWidget(close)
        box.addLayout(buttons)
        self.identifiers = ()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def present(self, entries, avatar):
        self.identifiers = tuple(entry["id"] for entry in entries)
        self.label.setText(entries[0]["title"] if len(entries) == 1 else f"有 {len(entries)} 条重要公告")
        self.adjustSize()
        bounds = avatar.screen().availableGeometry()
        x = max(bounds.left(), min(avatar.x() + avatar.width() - self.width(), bounds.right() - self.width() + 1))
        y = max(bounds.top(), min(avatar.y() - self.height() - 12, bounds.bottom() - self.height() + 1))
        self.move(x, y)
        self.show()
        self.timer.start(14000)

    def _open(self):
        identifier = self.identifiers[0] if len(self.identifiers) == 1 else ""
        self.hide()
        self.opened.emit(identifier)


class AnnouncementController(QObject):
    completed = Signal(object, str)

    def __init__(self, owner, path, source):
        super().__init__(owner.panel)
        self.owner = owner
        self.path = path
        self.source = source
        self.cache = AnnouncementCache.load(path)
        self.page = AnnouncementPage()
        self.bubble = AnnouncementBubble()
        self.future = None
        self.closed = False
        self.failures = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)
        self.completed.connect(self._finish)
        self.page.refresh_requested.connect(self.refresh)
        self.page.opened.connect(self.open_article)
        self.bubble.opened.connect(self.open)
        owner.panel.mount_section("announcements", self.page, on_open=self.refresh)
        self._render()
        self.timer.start(1000)

    def refresh(self):
        if self.closed or self.future is not None:
            return
        loop = self.owner.runtime.loop
        if not loop.is_running():
            self.timer.start(1000)
            return
        self.timer.stop()
        self.page.status.setText(self._with_last_sync("正在同步公告…"))
        self.future = asyncio.run_coroutine_threadsafe(
            fetch_announcements(self.source, self.cache.revision, self.cache.etag), loop)

        def finished(future):
            try:
                data, error = future.result(), ""
            except CancelledError:
                return
            except Exception as failure:
                LOG.info("公告同步未完成 type=%s", type(failure).__name__)
                data, error = None, "暂时无法同步，保留已缓存的公告"
            if not self.closed:
                self.completed.emit(data, error)

        self.future.add_done_callback(finished)

    def _with_last_sync(self, message):
        if not self.cache.synced_at:
            return message
        stamp = datetime.fromisoformat(self.cache.synced_at).astimezone().strftime("%m-%d %H:%M")
        return f"{message} · 上次同步 {stamp}"

    def _finish(self, delta, error):
        if self.closed:
            return
        self.future = None
        if not error:
            updated = self.cache.apply(delta)
            if self._save(updated):
                self.cache = updated
                self._render()
            else:
                error = "公告缓存写入失败"
        if error:
            self.failures = min(self.failures + 1, 5)
            delay = min(300, 15 * 2**self.failures)
            self.page.status.setText(self._with_last_sync(error))
        else:
            self.failures = 0
            delay = random.randint(285, 315)
            if self.page.status.text() != "这条公告已撤回":
                self.page.status.setText(self._with_last_sync("暂无已发布公告" if not self.cache.entries else "同步完成"))
        self.timer.start(delay * 1000)

    def _save(self, cache):
        try:
            cache.save(self.path)
            return True
        except OSError:
            LOG.warning("无法保存公告缓存")
            return False

    def _render(self):
        self.page.render(self.cache)
        self.owner.panel.navigation.set_announcement_unread(
            any(not entry["read"] for entry in self.cache.entries.values()))
        if self.bubble.isVisible() and any(key not in self.cache.entries for key in self.bubble.identifiers):
            self.bubble.hide()

    def open(self, identifier=""):
        if self.closed:
            return
        self.owner.panel.open_section("announcements")
        self.refresh()
        if identifier:
            self.open_article(identifier)
        else:
            self.page.offset = 0
            self.page.show_list()

    def open_article(self, identifier):
        entry = self.cache.entries.get(identifier)
        if entry is None:
            return
        self.page.show_article(entry)
        if not entry["read"]:
            self.cache.mark((identifier,), "read")
            self._save(self.cache)
            self._render()

    def remind(self, eligible):
        if self.closed or not eligible:
            self.bubble.hide()
            return
        if self.bubble.isVisible():
            return
        pending = self.cache.pending()
        if not pending:
            return
        ids = tuple(entry["id"] for entry in pending)
        self.cache.mark(ids, "reminded")
        if not self._save(self.cache):
            for identifier in ids:
                self.cache.entries[identifier]["reminded"] = False
            return
        self.bubble.present(pending, self.owner.avatar)

    def close(self):
        self.closed = True
        self.timer.stop()
        if self.future is not None:
            self.future.cancel()
        self.bubble.close()
