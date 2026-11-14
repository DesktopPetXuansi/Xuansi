"""首次配置的资源控件；只收集选择，不创建目录或下载文件。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton

from .ai.catalog import MODELS
from .settings_forms import field_row, form_group, form_hint


def resource_summary(plan, *, prepared=False):
    resources = []
    if plan.mode == "local":
        resources.extend(MODELS[model].name + "及看图组件"
                         for model in (plan.primary_model_id, *plan.backup_model_ids))
        backend = {"auto": "检测后确定", "cpu": "CPU", "cuda": "CUDA"}[plan.backend]
        resources.append(f"本机推理引擎（{backend}）")
    names = {"asr": "整句语音识别（SenseVoice）", "tts": "回复朗读（Melo / Kokoro）",
             "realtime": "实时语音识别（Paraformer）"}
    resources.extend(names[component] for component in plan.voice_components)
    prefix = "需要下载" if prepared else "初步估算（检查后确认）"
    return f"{prefix}：{plan.download_bytes / 2**20:.1f} MiB\n资源：" + ("、".join(resources) or "无需本地模型或语音资源")


def resource_widgets(dialog, layout, model_dir, components):
    form = form_group(layout, "准备本机资源")
    dialog.model_directory = QLineEdit(str(model_dir))
    dialog.model_directory.setAccessibleName("模型和语音保存位置")
    dialog.model_directory.setMaxLength(2048)
    browse = QPushButton("选择目录")

    def choose_directory():
        selected = QFileDialog.getExistingDirectory(dialog, "选择模型和语音保存位置",
                                                    dialog.model_directory.text())
        if selected:
            dialog.model_directory.setText(selected)

    browse.clicked.connect(choose_directory)
    directory = QHBoxLayout()
    directory.addWidget(dialog.model_directory)
    directory.addWidget(browse)
    form.addRow("模型和语音保存位置", directory)
    dialog.backend = QComboBox()
    for label, value in (("自动选择（推荐）", "auto"), ("NVIDIA 显卡（CUDA）", "cuda"),
                         ("处理器（CPU，可能较慢）", "cpu")):
        dialog.backend.addItem(label, value)
    dialog.backend.setCurrentIndex(dialog.backend.findData(dialog.ai.backend.currentData()))
    field_row(form, "本机加速方式", dialog.backend)
    dialog.backup = QCheckBox("同时准备实验 4B 备用模型（增加下载，效果仍待验证）")
    form.addRow(dialog.backup)
    dialog.voice = {}
    for component, title in (("asr", "整句语音识别（SenseVoice）"),
                             ("tts", "回复朗读（Melo / Kokoro）"),
                             ("realtime", "实时语音识别（Paraformer）")):
        box = QCheckBox(title)
        box.setChecked(component in components)
        form.addRow(box)
        dialog.voice[component] = box
    form_hint(form, "未勾选的组件不下载。录音默认关闭；安装资源不会自动开启麦克风。")
    form_hint(form, "在线服务与能力测试由服务商计费。确认配置后，下一步才会准备所选资源。")
    dialog.summary = QLabel()
    dialog.summary.setTextFormat(Qt.TextFormat.PlainText)
    dialog.summary.setWordWrap(True)
    form.addRow(dialog.summary)


def first_run_hints(page):
    """复用设置页时，明确首次配置尚未准备模型或提交设置。"""
    hints = {
        "local_only": "对话在本机运行，无在线对话费用；下一步会按选择准备本机模型。",
        "local_first": "优先使用本机模型，也需要验证在线备用服务；在线请求由服务商计费。",
        "online_first": "连接在线服务，无需下载本机对话模型；本机语音组件可以另行选择。",
    }
    page.policy_hint.setText(hints[page.policy.currentData()])
    for label in page.findChildren(QLabel):
        if label.text().startswith("测试成功后仍需点击“保存设置”"):
            label.setText("测试成功后还需在窗口底部检查并确认资源。更换服务商需重新填写密钥；取消测试不保证已产生的费用撤销。")
