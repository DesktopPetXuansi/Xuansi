"""同一用户的本地命名管道：重复启动只打开已有面板。"""

import hashlib
import logging
import time

from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .config import ROOT

LOG = logging.getLogger(__name__)
NAME = "neko-local-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]


def show_existing():
    connection = QLocalSocket()
    # 首次启动可能仍在装载 Qt/音频 DLL，等待已有实例完成管道初始化。
    connected = False
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        connection.connectToServer(NAME)
        if connection.waitForConnected(300):
            connected = True
            break
        connection.abort()
        time.sleep(0.1)
    connection.close()
    LOG.info("重复启动，已有面板通知=%s", connected)


def listen_for_launch(parent, on_launch):
    server = QLocalServer(parent)
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    QLocalServer.removeServer(NAME)

    def activate():
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            connection.close()
            connection.deleteLater()
        on_launch()

    server.newConnection.connect(activate)
    if not server.listen(NAME):
        LOG.warning("重复启动通知不可用，仍可点击桌宠或托盘打开面板")
    return server
