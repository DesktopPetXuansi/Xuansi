"""商店入口：在导入桌宠前选择独立、包外的用户数据目录。"""

import ctypes
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 用户目录下的独立文件夹不属于 MSIX 安装目录，也不自动删除旧版数据。
if "XUANSI_WRITABLE_ROOT" not in os.environ:
    os.environ["XUANSI_WRITABLE_ROOT"] = str(Path.home() / "Xuansi Store")


def run():
    try:
        from pet.store_bootstrap import main

        return main()
    except Exception as exc:
        # 启动边界只记录异常类别；失败时即使 Qt 尚未创建也能向用户说明。
        logging.getLogger(__name__).error("商店启动未完成，类别=%s", type(exc).__name__)
        ctypes.windll.user32.MessageBoxW(None, "玄司暂时无法启动，请在微软商店修复安装后重试。", "玄司", 0x10)
        return 1

if __name__ == "__main__":
    raise SystemExit(run())
