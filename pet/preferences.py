"""设置表单；保存事件统一构造经过校验的不可变设置。"""

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import Settings


class PersonaPage(QWidget):
    save_requested = Signal()

    def __init__(self, settings: Settings):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("让它成为你想要的伙伴"))
        form = QFormLayout()
        self.name = QLineEdit(settings.name)
        self.name.setMaxLength(40)
        form.addRow("名字", self.name)
        layout.addLayout(form)
        layout.addWidget(QLabel("人设 · 性格、称呼和相处方式"))
        self.persona = QPlainTextEdit(settings.persona)
        layout.addWidget(self.persona)
        layout.addWidget(QLabel("系统提示词 · 希望它始终遵守的回复习惯"))
        self.prompt = QPlainTextEdit(settings.system_prompt)
        layout.addWidget(self.prompt)
        self.save_button = QPushButton("保存人设与设置")
        self.save_button.clicked.connect(self.save_requested)
        layout.addWidget(self.save_button)

    def apply(self, settings):
        return replace(
            settings,
            name=self.name.text().strip(),
            persona=self.persona.toPlainText(),
            system_prompt=self.prompt.toPlainText(),
        )


class PreferencesPage(QWidget):
    save_requested = Signal()
    preview_requested = Signal()

    def __init__(self, settings: Settings):
        super().__init__()
        form = QFormLayout(self)
        self.observe = QCheckBox("结合屏幕画面理解鼠标操作")
        self.observe.setChecked(settings.observe)
        self.follow = QCheckBox("跟随鼠标走动（关闭时停在原地）")
        self.follow.setChecked(settings.follow_mouse)
        self.speak = QCheckBox("默认朗读对话回复")
        self.speak.setChecked(settings.speak_replies)
        self.speak.setToolTip("对话中可让模型理解并切换朗读；重启或保存设置后恢复这里的偏好。")
        self.proactive = QCheckBox("也朗读主动观察的回应")
        self.proactive.setChecked(settings.speak_observations)
        self.realtime = QCheckBox("实时识别（说完后尽快回复）")
        self.realtime.setChecked(settings.realtime_voice)
        self.realtime.setToolTip("说话时识别文字，结束后才回复。关闭后使用原来的整句识别。")
        for widget in (self.observe, self.follow, self.speak, self.proactive, self.realtime):
            form.addRow(widget)
        self.capture_scope = QComboBox()
        self.capture_scope.addItem("整块屏幕 · 鼠标所在显示器", "screen")
        self.capture_scope.addItem("鼠标附近 · 局部画面", "nearby")
        self.capture_scope.setCurrentIndex(self.capture_scope.findData(settings.capture_scope))
        form.addRow("观察范围", self.capture_scope)
        note = QLabel("整屏会保留完整画面，长边最多 1600 像素；所有图像仅在本机内存中处理。")
        note.setWordWrap(True)
        note.setObjectName("hint")
        form.addRow(note)
        self.interval = QSpinBox()
        self.interval.setRange(10, 300)
        self.interval.setSuffix(" 秒")
        self.interval.setValue(settings.interval)
        form.addRow("观察间隔", self.interval)
        self.size = QComboBox()
        for label, value in [
            ("迷你 · 64", 64),
            ("小 · 96", 96),
            ("紧凑 · 128", 128),
            ("中 · 160", 160),
            ("大 · 224", 224),
            ("特大 · 288", 288),
        ]:
            self.size.addItem(label, value)
        self.size.setCurrentIndex(self.size.findData(settings.pet_size))
        form.addRow("桌宠大小", self.size)
        self.tts_engine = QComboBox()
        self.tts_engine.addItem("Melo 中英 · 默认", "fast")
        self.tts_engine.addItem("Kokoro 中英 · 音色更丰富，较慢", "natural")
        self.tts_engine.setCurrentIndex(self.tts_engine.findData(settings.tts_engine))
        form.addRow("语音方案", self.tts_engine)
        self.speaker = QSpinBox()
        self.speaker.setRange(0, 0 if settings.tts_engine == "fast" else 102)
        self.speaker.setValue(settings.speaker)
        self.speaker.setEnabled(settings.tts_engine != "fast")
        self.tts_engine.currentIndexChanged.connect(self._voice_engine_changed)
        form.addRow("本地音色编号", self.speaker)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.7, 1.5)
        self.speed.setSingleStep(0.05)
        self.speed.setValue(settings.speed)
        form.addRow("说话速度", self.speed)
        preview = QPushButton("试听当前音色")
        preview.clicked.connect(self.preview_requested)
        form.addRow(preview)
        self.device = QComboBox()
        self.device.addItem("系统默认麦克风", -1)
        form.addRow("麦克风", self.device)
        hint = QLabel(
            "麦克风需手动开启；全屏时暂停观察。\n休眠会关闭麦克风并释放模型，恢复后需再次开启对话。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        form.addRow(hint)
        self.save_button = QPushButton("保存设置")
        self.save_button.clicked.connect(self.save_requested)
        form.addRow(self.save_button)

    def set_devices(self, devices, selected):
        self.device.clear()
        self.device.addItem("系统默认麦克风", -1)
        for index, name in devices:
            self.device.addItem(name, index)
        self.device.setCurrentIndex(max(0, self.device.findData(selected)))

    def _voice_engine_changed(self):
        natural = self.tts_engine.currentData() == "natural"
        self.speaker.setMaximum(102 if natural else 0)
        self.speaker.setEnabled(natural)
        self.speaker.setValue(46 if natural else 0)

    def apply(self, settings):
        return replace(
            settings,
            observe=self.observe.isChecked(),
            capture_scope=self.capture_scope.currentData(),
            follow_mouse=self.follow.isChecked(),
            speak_replies=self.speak.isChecked(),
            speak_observations=self.proactive.isChecked(),
            realtime_voice=self.realtime.isChecked(),
            interval=self.interval.value(),
            pet_size=self.size.currentData(),
            speaker=self.speaker.value(),
            speed=float(self.speed.value()),
            input_device=self.device.currentData(),
            tts_engine=self.tts_engine.currentData(),
        )
