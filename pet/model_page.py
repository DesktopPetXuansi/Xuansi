"""可保存的模型配置；表单提示资源成本，实际参数由推理层使用。"""

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)


class ModelPage(QWidget):
    save_requested = Signal()

    def __init__(self, settings):
        super().__init__()
        form = QFormLayout(self)
        hint = QLabel("调整回复与资源占用。保存会结束当前回复并关闭麦克风，下次回应使用新参数。")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0, 2)
        self.temperature.setSingleStep(0.1)
        self.temperature.setValue(settings.temperature)
        form.addRow("随机性 temperature", self.temperature)
        self.top_p = QDoubleSpinBox()
        self.top_p.setRange(0.01, 1)
        self.top_p.setSingleStep(0.05)
        self.top_p.setValue(settings.top_p)
        form.addRow("采样范围 top_p", self.top_p)
        self.tokens = QSpinBox()
        self.tokens.setRange(32, 1024)
        self.tokens.setValue(settings.max_tokens)
        form.addRow("回复 token 上限", self.tokens)
        self.context = QComboBox()
        for size in (4096, 8192, 16384):
            self.context.addItem(str(size), size)
        self.context.setCurrentIndex(self.context.findData(settings.context_size))
        form.addRow("上下文 token 数", self.context)
        self.threads = QSpinBox()
        self.threads.setRange(1, 8)
        self.threads.setValue(settings.cpu_threads)
        form.addRow("CPU 线程数", self.threads)
        self.layers = QSpinBox()
        self.layers.setRange(0, 99)
        self.layers.setValue(settings.gpu_layers)
        form.addRow("GPU 层数（0 为 CPU）", self.layers)
        self.model = self._file_row(form, "图文模型 GGUF", settings.model_path)
        self.projector = self._file_row(form, "视觉组件 GGUF", settings.projector_path)
        hint = QLabel(
            "模型与视觉组件需配套。增大上下文会增加显存占用；\n建议从默认 4096 上下文、4 个 CPU 线程开始。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        form.addRow(hint)
        self.hotkey = QKeySequenceEdit(QKeySequence(settings.chat_hotkey))
        self.hotkey.setMaximumSequenceLength(1)
        form.addRow("右下角对话快捷键", self.hotkey)
        hint = QLabel(
            "点选后按下新组合，至少两个修饰键。再次按热键或 Esc 隐藏。\n其他软件发声时只显示文字；安静后不补播旧回复。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        form.addRow(hint)
        self.save_button = QPushButton("保存配置")
        self.save_button.clicked.connect(self.save_requested)
        form.addRow(self.save_button)

    def _file_row(self, form, label, value):
        row = QHBoxLayout()
        field = QLineEdit(value)
        field.setMaxLength(1024)
        row.addWidget(field)
        button = QPushButton("选择")
        button.clicked.connect(lambda: self._choose(field))
        row.addWidget(button)
        form.addRow(label, row)
        return field

    def _choose(self, field):
        path, _ = QFileDialog.getOpenFileName(self, "选择本地模型", field.text(), "GGUF 模型 (*.gguf)")
        if path:
            field.setText(path)

    def apply(self, settings):
        return replace(
            settings,
            temperature=float(self.temperature.value()),
            top_p=float(self.top_p.value()),
            max_tokens=self.tokens.value(),
            context_size=self.context.currentData(),
            cpu_threads=self.threads.value(),
            gpu_layers=self.layers.value(),
            model_path=self.model.text().strip(),
            projector_path=self.projector.text().strip(),
            chat_hotkey=self.hotkey.keySequence().toString(QKeySequence.SequenceFormat.PortableText),
        )
