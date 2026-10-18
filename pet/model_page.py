"""可保存的模型配置；表单提示资源成本，实际参数由推理层使用。"""

import logging
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .ai_page import AIPage
from .settings_forms import field_row, form_group, form_hint

LOG = logging.getLogger(__name__)


class ModelPage(QWidget):
    save_requested = Signal()

    def __init__(self, settings):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        hint = QLabel("调整回复与资源占用。保存会结束当前回复并关闭麦克风，下次回应使用新参数。")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        layout.addWidget(hint)
        self.ai_page = AIPage(settings.ai)
        layout.addWidget(self.ai_page)
        reply = form_group(layout, "回复参数")
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0, 2)
        self.temperature.setSingleStep(0.1)
        self.temperature.setValue(settings.temperature)
        field_row(reply, "随机性 temperature", self.temperature)
        self.top_p = QDoubleSpinBox()
        self.top_p.setRange(0.01, 1)
        self.top_p.setSingleStep(0.05)
        self.top_p.setValue(settings.top_p)
        field_row(reply, "采样范围 top_p", self.top_p)
        self.tokens = QSpinBox()
        self.tokens.setRange(32, 1024)
        self.tokens.setValue(settings.max_tokens)
        field_row(reply, "回复 token 上限", self.tokens)
        resources = form_group(layout, "资源占用")
        self.context = QComboBox()
        for size in (4096, 8192, 16384):
            self.context.addItem(str(size), size)
        self.context.setCurrentIndex(self.context.findData(settings.context_size))
        field_row(resources, "上下文 token 数", self.context)
        self.threads = QSpinBox()
        self.threads.setRange(1, 8)
        self.threads.setValue(settings.cpu_threads)
        field_row(resources, "CPU 线程数", self.threads)
        self.layers = QSpinBox()
        self.layers.setRange(0, 99)
        self.layers.setValue(settings.gpu_layers)
        self.layers.setToolTip('99 为自动GPU分配并保留显存余量；0 使用CPU；1–98保持精确手调。')
        field_row(resources, "GPU 层数（0 为 CPU）", self.layers)
        form_hint(
            resources,
            "增大上下文会增加显存占用；建议从默认 4096 上下文、4 个 CPU 线程开始。",
        )
        local = form_group(layout, "本地模型")
        self.model = self._file_row(local, "图文模型 GGUF", settings.model_path)
        self.projector = self._file_row(local, "视觉组件 GGUF", settings.projector_path)
        self.ai_page.local_model.currentIndexChanged.connect(self._local_model_changed)
        self.ai_page.model_dir.editingFinished.connect(self._local_model_changed)
        form_hint(local, "模型与视觉组件需配套。路径可直接编辑，悬停可查看完整路径。")
        hotkeys = form_group(layout, "快捷键")
        self.hotkey = QKeySequenceEdit(QKeySequence(settings.chat_hotkey))
        self.hotkey.setMaximumSequenceLength(1)
        field_row(hotkeys, "控制中心快捷键", self.hotkey)
        form_hint(
            hotkeys,
            "点选后按下新组合，至少两个修饰键。再次按快捷键或 Esc 收起控制中心。\n收起时保存未保存的配置；安静后不补播声音回避期间的旧回复。"
        )
        self.save_button = QPushButton("保存设置")
        self.save_button.clicked.connect(self.save_requested)
        layout.addWidget(self.save_button)
        layout.addStretch()
        LOG.debug("模型设置页已就绪")

    def _file_row(self, form, label, value):
        row = QHBoxLayout()
        field = QLineEdit(value)
        field.setMaxLength(1024)
        field.setMinimumWidth(0)
        field.setAccessibleName(label)
        field.setToolTip(value)
        # 完整路径仅用于本机界面显示，不写入运行日志。
        field.textChanged.connect(field.setToolTip)
        row.addWidget(field)
        button = QPushButton("选择")
        button.setAccessibleName("选择" + label)
        button.clicked.connect(lambda: self._choose(field))
        row.addWidget(button)
        title = QLabel(label)
        title.setBuddy(field)
        form.addRow(title, row)
        return field

    def _choose(self, field):
        path, _ = QFileDialog.getOpenFileName(self, "选择本地模型", field.text(), "GGUF 模型 (*.gguf)")
        if path:
            field.setText(path)

    def apply(self, settings):
        return replace(
            settings,
            ai=self.ai_page.apply(settings.ai),
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

    def _local_model_changed(self, *_):
        from .ai.catalog import MODELS
        from .config import MODELS as DEFAULT_MODELS

        model = MODELS.get(self.ai_page.local_model.currentData())
        if model is None:
            return
        # 仅响应用户修改；初始化必须保留已有自定义配套路径。
        directory = Path(self.ai_page.model_dir.text().strip() or DEFAULT_MODELS)
        self.model.setText(str(directory / model.model_path))
        self.projector.setText(str(directory / model.projector_path))
        LOG.info("本地模型档位已修改，配套路径已更新")

    def credential_changed(self):
        return self.ai_page.credential_changed()

    def credential_draft(self):
        return self.ai_page.credential_draft()

    def credentials_saved(self, snapshot):
        self.ai_page.credentials_saved(snapshot)
