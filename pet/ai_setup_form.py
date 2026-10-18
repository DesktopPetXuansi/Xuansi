"""模型设置的原生表单布局；常用步骤与高级参数共用现有配置控件。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .ai.catalog import MODELS
from .ai.provider_catalog import preset_profiles
from .settings_forms import AdvancedSettings, field_row, form_group, form_hint

SERVICE_NAMES = {
    "openai": "OpenAI", "bailian": "阿里云百炼", "deepseek": "DeepSeek", "kimi": "Kimi",
    "zhipu": "智谱", "doubao": "火山方舟", "claude": "Claude", "gemini": "Google Gemini",
}
REGION_NAMES = {"global": "国际", "cn": "中国内地", "cn-beijing": "中国内地", "singapore": "新加坡"}
# 仅使用官方文档核实的获取入口；百炼指南同时说明中国内地与国际地域。
KEY_LINKS = {
    "openai": "https://platform.openai.com/api-keys",
    "bailian": "https://help.aliyun.com/zh/model-studio/get-api-key",
    "deepseek": "https://platform.deepseek.com/api_keys",
    "kimi": "https://platform.kimi.com/console/api-keys",
    "zhipu": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
    "doubao": "https://console.volcengine.com/ark",
    "claude": "https://platform.claude.com/settings/keys",
    "gemini": "https://aistudio.google.com/apikey",
}


def create_setup_form(page, settings):
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(16)
    run = form_group(layout, "选择运行方式")
    page.policy = QComboBox()
    for title, value in (("本机运行", "local_only"), ("本机优先，在线备用", "local_first"),
                         ("在线优先", "online_first")):
        page.policy.addItem(title, value)
    page.policy.setCurrentIndex(page.policy.findData(settings.policy))
    field_row(run, "对话使用", page.policy)
    page.policy_hint = form_hint(run, "")
    _local_form(page, layout, settings)
    _online_form(page, layout)
    _privacy_form(page, layout, settings)
    page.advanced = AdvancedSettings()
    layout.addWidget(page.advanced)
    _local_parameters(page, page.advanced.content_layout, settings)
    _online_parameters(page, page.advanced.content_layout)


def _local_form(page, layout, settings):
    local = form_group(layout, "本机模型")
    page.local_group = local.parentWidget()
    page.local_model = QComboBox()
    page.local_model.addItem("标准 · Qwen3.5 9B", "qwen3.5-9b")
    light_status = "回答和操作可能不可靠" if MODELS["qwen3.5-4b"].verification == "failed" else "效果待验证"
    page.local_model.addItem(f"轻量 · Qwen3.5 4B（实验：{light_status}）", "qwen3.5-4b")
    page.local_model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    page.local_model.setMinimumContentsLength(12)
    if page.local_model.findData(settings.local_model) < 0:
        page.local_model.addItem(settings.local_model, settings.local_model)
    page.local_model.setCurrentIndex(page.local_model.findData(settings.local_model))
    field_row(local, "模型", page.local_model)
    page.detect = QPushButton("检测电脑并推荐")
    page.detect.clicked.connect(page.probe)
    local.addRow(page.detect)
    page.device_status = form_hint(local, "检测后会给出配置建议；只估算资源，实际回复速度需运行后确认。")


def _online_form(page, layout):
    online = form_group(layout, "连接在线服务")
    page.online_group = online.parentWidget()
    page.presets = QComboBox()
    page.presets.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    page.presets.setMinimumContentsLength(12)
    page.presets.addItem("选择服务商，或在高级设置中自定义", None)
    for profile in preset_profiles():
        title = f"{SERVICE_NAMES[profile.provider]} · {REGION_NAMES[profile.region]} · {profile.model}"
        page.presets.addItem(title, profile)
    field_row(online, "1. 选择服务商", page.presets)
    page.online_model = form_hint(online, "")
    page.online_model.setTextFormat(Qt.TextFormat.PlainText)
    page.key = QLineEdit()
    page.key.setEchoMode(QLineEdit.EchoMode.Password)
    page.key.setMaxLength(4096)
    page.key.setPlaceholderText("粘贴密钥；留空保留当前服务已保存的密钥")
    field_row(online, "2. API 密钥", page.key)
    page.key_help = form_hint(online, "从服务商的控制台获取密钥。保存后存入本机系统凭据管理器。")
    page.key_help.setOpenExternalLinks(True)
    form_hint(online, "在线对话与测试由服务商直接计费；测试可能产生少量费用。测试使用示例资料，不读取屏幕、录音或记忆。")
    page.validate_button = QPushButton("3. 测试可用性")
    page.validate_button.clicked.connect(page.start_validation)
    page.cancel_button = QPushButton("取消测试")
    page.cancel_button.clicked.connect(page.cancel_validation)
    page.cancel_button.setEnabled(False)
    online.addRow(page.validate_button, page.cancel_button)
    page.validation_status = form_hint(online, "")
    form_hint(online, "测试成功后仍需点击“保存设置”。更换服务商需重新填写密钥；取消测试不保证已产生的费用撤销。")


def _privacy_form(page, layout, settings):
    privacy = form_group(layout, "在线服务可以接收哪些资料")
    page.privacy_group = privacy.parentWidget()
    form_hint(privacy, "在线对话会发送文字、必要的对话记录、工具结果和明确附加的图片。以下两项分别授权，默认关闭。")
    page.cloud_memory = QCheckBox("允许在线服务读取长期记忆")
    page.cloud_memory.setChecked(settings.cloud_memory)
    privacy.addRow(page.cloud_memory)
    form_hint(privacy, "开启后可能分批发送整个记忆库，不只发送最终找到的摘录；记忆文件仍保存在本机。")
    page.cloud_observation = QCheckBox("允许自动观察时向在线服务发送屏幕截图")
    page.cloud_observation.setChecked(settings.cloud_observation)
    privacy.addRow(page.cloud_observation)
    form_hint(privacy, "关闭只限制自动观察；手动附图和对话中按需截图仍可使用。录音在本机识别，不发送给在线模型。")


def _local_parameters(page, layout, settings):
    local = form_group(layout, "本机加速与文件位置")
    page.backend = QComboBox()
    for title, value in (("自动选择（推荐）", "auto"), ("NVIDIA 显卡（CUDA）", "cuda"), ("处理器（CPU，可能较慢）", "cpu")):
        page.backend.addItem(title, value)
    page.backend.setCurrentIndex(page.backend.findData(settings.local_backend))
    field_row(local, "加速方式", page.backend)
    page.model_dir = _path(local, "模型保存位置", settings.model_dir, directory=True)
    page.backup_model = _path(local, "已安装的备用模型（GGUF）", settings.backup_model_path)
    page.backup_projector = _path(local, "备用看图组件（GGUF）", settings.backup_projector_path)
    form_hint(local, "备用模型和看图组件需配套安装。运行中不会自动下载；更换模型或保存位置后，请检查下方文件路径。")
    page.device_details = form_hint(local, "尚未检测电脑配置。")


def _online_parameters(page, layout):
    online = form_group(layout, "在线服务的自定义参数")
    form_hint(online, "选择服务商后会自动填写。仅使用自定义服务、模型或特殊接入方式时修改；能力声明还需通过测试。")
    for name, title in (("provider", "服务商标识"), ("region", "服务地区"), ("endpoint", "API 地址"),
                        ("model", "模型名称（ID）"), ("mode", "工作模式")):
        field = QLineEdit()
        field.setMaxLength(2048)
        setattr(page, name, field)
        field_row(online, title, field)
    page.context_tokens = QSpinBox()
    page.context_tokens.setRange(1024, 2_000_000)
    field_row(online, "对话容量（token）", page.context_tokens)
    page.capabilities = {}
    for name, title in (("text", "文字聊天"), ("image", "看图"), ("tools", "使用工具"),
                        ("stream", "逐步显示回复"), ("cancel", "取消请求"), ("json", "JSON 结构化输出")):
        box = QCheckBox("服务商声明支持：" + title)
        page.capabilities[name] = box
        online.addRow(box)


def _path(form, title, value, directory=False):
    row = QHBoxLayout()
    field = QLineEdit(value)
    field.setMaxLength(2048)
    field.setAccessibleName(title)
    field.setToolTip(value)
    # 完整路径仅在本机提示中显示，不写入运行日志。
    field.textChanged.connect(field.setToolTip)
    row.addWidget(field)
    button = QPushButton("选择")
    button.setAccessibleName("选择" + title)

    def choose():
        path = (QFileDialog.getExistingDirectory(field, title, field.text()) if directory else
                QFileDialog.getOpenFileName(field, title, field.text(), "GGUF (*.gguf)")[0])
        if path:
            field.setText(path)

    button.clicked.connect(choose)
    row.addWidget(button)
    form.addRow(title, row)
    return field
