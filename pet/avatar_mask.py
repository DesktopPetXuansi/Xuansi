"""缓存帧选择与窗口点击蒙版；透明区域继续让出下层应用。"""

from PySide6.QtGui import QRegion

LIVE2D_MASK_PADDING_RATIO = 0.03125


def _expand_mask_region(region, padding):
    """扩展 Live2D 点击区域，给模型移动后的抗锯齿发丝留出空间。"""
    padding = max(0, int(padding))
    if padding == 0 or region.isEmpty():
        return region

    horizontal = QRegion()
    for offset in range(-padding, padding + 1):
        horizontal = horizontal.united(region.translated(offset, 0))

    expanded = QRegion()
    for offset in range(-padding, padding + 1):
        expanded = expanded.united(horizontal.translated(0, offset))
    return expanded


class AvatarMask:
    """缓存帧选择与窗口点击蒙版；透明区域继续让出下层应用。"""

    def _live2d_window_mask(self):
        """按窗口高度扩展原图点击轮廓，避免高 DPI 或改尺寸后缓冲失衡。"""
        padding = max(2, round(self.height() * LIVE2D_MASK_PADDING_RATIO))
        return _expand_mask_region(self.frames["idle"][0][1], padding)

    def _pixmap(self):
        frames = self.frames[self.animation]
        return frames[self.frame % len(frames)][0]

    def _frame_mask(self):
        # 原生窗口形状只覆盖非透明像素，外围矩形不会挡住下面的程序。
        if self._live2d_active:
            return
        key = "idle" if self.native_animation else self.animation, self.frame % len(self.durations)
        if key == self._shown_frame:
            return
        self._shown_frame = key
        region = self.frames[key[0]][key[1]][1]
        # 空区域在 Qt 表示“清除蒙版”；透明帧应使用窗外区域，不能挡住下层应用。
        self.setMask(region if not region.isEmpty() else QRegion(-1, -1, 1, 1))
        if hasattr(self, "clock"):
            self.clock.setInterval(self.durations[key[1]])
        self.update()
