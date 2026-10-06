"""共享 Cubism 核心与着色器；单个窗口只释放自己的模型。"""

import logging
from weakref import WeakSet

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QOpenGLContext

LOG = logging.getLogger(__name__)


def configure_opengl_sharing():
    """在创建 QApplication 前开启跨顶层窗口共享，供桌宠和预览复用着色器。"""
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)


class Live2DSession:
    def __init__(self):
        self.owners = WeakSet()
        self.module = None
        self.gl_ready = False
        self.disposed = False

    def acquire(self, owner, module):
        """仅在当前 GL 上下文中调用；模型各自独立，SDK 在应用中只初始化一次。"""
        if self.disposed:
            raise RuntimeError("Live2D 应用会话已经结束")
        context = owner.context()
        for existing in self.owners:
            other = existing.context()
            if context is not None and other is not None and not QOpenGLContext.areSharing(context, other):
                raise RuntimeError("Live2D 窗口未共享 OpenGL 资源，请重新启动桌宠")
        if self.module is None:
            module.enableLog(True)
            module.init()
            self.module = module
            application = QCoreApplication.instance()
            if application is not None:
                application.aboutToQuit.connect(self.shutdown)
            LOG.info("Live2D 共享应用会话已初始化")
        if not self.gl_ready:
            module.glInit()
            self.gl_ready = True
        self.owners.add(owner)
        LOG.info("Live2D 模型资源已登记 windows=%s", len(self.owners))

    def release(self, owner):
        """最后一个模型释放后清除公共着色器；保留核心以支持重新打开预览。"""
        if owner not in self.owners:
            return
        self.owners.remove(owner)
        if not self.owners:
            self.module.glRelease()
        LOG.info("Live2D 模型资源已归还 windows=%s", len(self.owners))

    def shutdown(self):
        """应用退出时先销毁所有模型，再释放 Cubism；不能提前使其他窗口失效。"""
        if self.module is None or self.disposed:
            return
        for owner in tuple(self.owners):
            owner._release_live2d()
        self.module.dispose()
        self.disposed = True
        LOG.info("Live2D 共享应用会话已释放")


SESSION = Live2DSession()
