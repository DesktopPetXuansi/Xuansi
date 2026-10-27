"""设置表单；保存事件统一构造经过校验的不可变设置。"""

import logging
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
from .settings_forms import field_row, form_group, form_hint

LOG = logging.getLogger(__name__)


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
        layout.addWidget(QLabel("回复习惯 · 希望它始终遵守的要求"))
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
        self.observe = QCheckBox("结合屏幕画面理解鼠标操作")
        self.observe.setChecked(settings.observe)
        self.follow = QCheckBox("跟随鼠标走动（关闭时停在原地）")
        self.follow.setChecked(settings.follow_mouse)
        self.speak = QCheckBox("默认朗读对话回复")
        self.speak.setChecked(settings.speak_replies)
        self.speak.setToolTip("对话中可让模型理解并切换朗读；重启或保存设置后恢复这里的偏好。")
        self.proactive = QCheckBox("也朗读主动观察的回应")
        self.proactive.setChecked(settings.speak_observations)
        self.realtime = QCheckBox("边说边显示文字，说完再回复")
        self.realtime.setChecked(settings.realtime_voice)
        self.realtime.setToolTip("开启后边说边识别文字，结束后才回复；关闭后等说完再识别。")
        self.capture_scope = QComboBox()
        self.capture_scope.addItem("整块屏幕 · 鼠标所在显示器", "screen")
        self.capture_scope.addItem("鼠标附近 · 局部画面", "nearby")
        self.capture_scope.setCurrentIndex(self.capture_scope.findData(settings.capture_scope))
        self.interval = QSpinBox()
        self.interval.setRange(10, 300)
        self.interval.setSuffix(" 秒")
        self.interval.setValue(settings.interval)
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
        self.tts_engine = QComboBox()
        self.tts_engine.addItem("快速朗读 · 中文和英文（Melo）", "fast")
        self.tts_engine.addItem("更多音色 · 速度较慢（Kokoro）", "natural")
        self.tts_engine.setCurrentIndex(self.tts_engine.findData(settings.tts_engine))
        self.speaker = QSpinBox()
        self.speaker.setRange(0, 0 if settings.tts_engine == "fast" else 102)
        self.speaker.setValue(settings.speaker)
        self.speaker.setEnabled(settings.tts_engine != "fast")
        self.speaker.setToolTip("快速朗读只有一种音色；更多音色可选 0–102，修改后点击试听。")
        self._natural_speaker = settings.speaker if settings.tts_engine == "natural" else 46
        self.tts_engine.currentIndexChanged.connect(self._voice_engine_changed)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.7, 1.5)
        self.speed.setSingleStep(0.05)
        self.speed.setValue(settings.speed)
        preview = QPushButton("试听当前音色")
        preview.clicked.connect(self.preview_requested)
        self.device = QComboBox()
        self.device.addItem("系统默认麦克风", -1)
        self._initial_device = settings.input_device
        if settings.input_device != -1:
            self.device.addItem("已保存的麦克风（等待设备列表）", settings.input_device)
            self.device.setCurrentIndex(1)
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        sound = form_group(layout, "声音")
        sound.addRow(self.speak)
        sound.addRow(self.proactive)
        field_row(sound, "朗读方式", self.tts_engine)
        field_row(sound, "音色编号", self.speaker)
        form_hint(sound, "快速朗读无需选择音色；更多音色通过编号选择，可点击下方按钮试听。")
        field_row(sound, "说话速度", self.speed)
        sound.addRow(preview)
        form_hint(sound, "这里设置默认朗读偏好；对话中的朗读开关会在保存设置或重启后恢复。")

        microphone = form_group(layout, "麦克风")
        microphone.addRow(self.realtime)
        field_row(microphone, "使用的麦克风", self.device)
        form_hint(microphone, "麦克风需手动开启。休眠暂停收音，唤醒后恢复原来已开启的连续对话。")

        behavior = form_group(layout, "观察与行为")
        behavior.addRow(self.observe)
        field_row(behavior, "观察范围", self.capture_scope)
        form_hint(behavior, "全屏应用运行时暂停观察。使用在线模型时，自动发送屏幕画面需在模型设置中单独允许；手动附图会发给当前模型。")
        field_row(behavior, "观察间隔", self.interval)
        behavior.addRow(self.follow)
        field_row(behavior, "桌宠大小", self.size)
        for checkbox in (self.observe, self.follow, self.speak, self.proactive, self.realtime):
            checkbox.setAccessibleName(checkbox.text())
        self.save_button = QPushButton("保存设置")
        self.save_button.setToolTip("保存后结束当前回复并关闭麦克风；朗读恢复这里设置的默认偏好。")
        self.save_button.clicked.connect(self.save_requested)
        layout.addWidget(self.save_button)
        layout.addStretch()
        # 控件按原有顺序构造以保留初始化行为，键盘顺序与新的任务分组一致。
        tab_order = (
            self.speak, self.proactive, self.tts_engine, self.speaker, self.speed, preview,
            self.realtime, self.device, self.observe, self.capture_scope, self.interval,
            self.follow, self.size, self.save_button,
        )
        for previous, following in zip(tab_order, tab_order[1:]):
            QWidget.setTabOrder(previous, following)
        # 未安装的朗读组件保留已有偏好，仅禁用入口。
        if "tts" not in settings.ai.voice_components:
            for widget in (self.speak, self.proactive, self.tts_engine, self.speaker, self.speed, preview):
                widget.setEnabled(False)
                widget.setToolTip("未安装朗读组件，请通过安装器添加后使用。")
        asr_installed = "asr" in settings.ai.voice_components
        realtime_installed = "realtime" in settings.ai.voice_components
        if not (asr_installed or realtime_installed):
            for widget in (self.realtime, self.device):
                widget.setEnabled(False)
                widget.setToolTip("未安装语音识别组件，请通过安装器添加后使用。")
        elif not (asr_installed and realtime_installed):
            # 单组件模式必须与实际资源一致，不能被旧的另一模式偏好锁死。
            self.realtime.setChecked(realtime_installed)
            self.realtime.setEnabled(False)
            self.realtime.setToolTip("仅安装实时识别组件，固定使用实时识别。" if realtime_installed
                                     else "仅安装整句识别组件，固定使用整句识别。")
            LOG.info("语音识别模式按已安装组件固定 realtime=%s", realtime_installed)
        LOG.debug("语音与行为设置页已就绪")

    def set_devices(self, devices, selected):
        # 异步枚举不得覆盖已保存设备，也不得覆盖等待期间用户新选的设备。
        if self.device.currentData() != self._initial_device:
            selected = self.device.currentData()
        self.device.clear()
        self.device.addItem("系统默认麦克风", -1)
        for index, name in devices:
            self.device.addItem(name, index)
        if self.device.findData(selected) < 0:
            self.device.addItem("已保存的麦克风（当前不可用，请检查连接）", selected)
            LOG.info("保留暂不可用的麦克风选择 device=%s", selected)
        self.device.setCurrentIndex(self.device.findData(selected))
        self._initial_device = selected

    def _voice_engine_changed(self):
        natural = self.tts_engine.currentData() == "natural"
        if not natural:
            # 缩小范围会把控件值截成 0，先保留本次表单的自然音色草稿。
            self._natural_speaker = self.speaker.value()
        self.speaker.setMaximum(102 if natural else 0)
        self.speaker.setEnabled(natural)
        self.speaker.setValue(self._natural_speaker if natural else 0)
        LOG.debug("朗读方式已切换 engine=%s speaker=%s", self.tts_engine.currentData(), self.speaker.value())

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
