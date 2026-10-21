"""用户主动反馈的数据边界；诊断只含固定版本字段，不读取用户内容。"""

import platform
from dataclasses import dataclass

from PySide6.QtCore import qVersion

from .config import ROOT

CATEGORIES = {"BUG": "使用问题", "SUGGESTION": "功能建议", "OTHER": "其他反馈"}
DIAGNOSTIC_LABELS = {
    "appVersion": "软件版本", "system": "操作系统", "architecture": "系统架构",
    "pythonVersion": "Python版本", "qtVersion": "Qt版本",
}


@dataclass(frozen=True)
class FeedbackDraft:
    category: str
    title: str
    description: str
    contact: str = ""
    diagnostics: dict[str, str] | None = None
    public_consent: bool = False

    def payload(self):
        if self.category not in CATEGORIES:
            raise ValueError("请选择反馈类型。")
        if not isinstance(self.public_consent, bool):
            raise ValueError("公开反馈的同意选项无效，请重新确认。")
        data = {"category": self.category}
        # 只有用户明确授权时才携带公开许可；旧客户端缺省仍为私有。
        if self.public_consent:
            data["publicConsent"] = True
        for field, text, limit, label in (
            ("title", self.title, 80, "标题"), ("description", self.description, 4000, "具体说明"),
            ("contact", self.contact, 160, "联系方式"),
        ):
            if not isinstance(text, str) or "\0" in text:
                raise ValueError(f"{label}包含无法处理的字符。")
            text = text.strip()
            if (field != "contact" and not text) or len(text) > limit:
                raise ValueError(f"请填写{label}，最多{limit}字。")
            if text:
                data[field] = text
        if self.diagnostics is not None:
            if (not self.diagnostics or not set(self.diagnostics) <= DIAGNOSTIC_LABELS.keys()
                    or any(not isinstance(value, str) or not value or len(value) > 80 or "\0" in value
                           for value in self.diagnostics.values())):
                raise ValueError("版本信息暂不可用，可取消勾选后提交。")
            data["diagnostics"] = dict(self.diagnostics)
        return data

    def copy_text(self):
        data = self.payload()
        lines = [f"反馈类型：{CATEGORIES[self.category]}", f"标题：{data['title']}", "", data["description"]]
        lines.extend(("", "公开范围：标题、具体说明及勾选的版本和系统信息可公开至 GitHub DesktopPetXuansi/Xuansi。"
                      if self.public_consent else "公开范围：未同意公开，仅私有保存。"))
        if data.get("contact"):
            lines.extend(("", f"联系方式（仅私有保存）：{data['contact']}"))
        if self.diagnostics:
            lines.extend(("", "版本与系统信息：", diagnostic_text(self.diagnostics)))
        return "\n".join(lines)


def diagnostic_text(values):
    return "\n".join(f"{label}：{values[key]}" for key, label in DIAGNOSTIC_LABELS.items() if key in values)


def collect_diagnostics():
    # 调用方在后台线程执行；不读settings、日志、设备名、对话、记忆或屏幕。
    try:
        version = (ROOT / "VERSION").read_text(encoding="utf-8-sig").strip()
    except OSError:
        version = "开发版本"
    values = {
        "appVersion": version, "system": f"{platform.system()} {platform.release()} ({platform.version()})",
        "architecture": platform.machine(), "pythonVersion": platform.python_version(), "qtVersion": qVersion(),
    }
    return {key: (value or "未知")[:80] for key, value in values.items()}
