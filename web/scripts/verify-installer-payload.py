"""用真实 Inno 编译器验证桌面载荷排除官网，测试不安装软件或修改注册表。"""

import argparse
import logging
import subprocess
import tempfile
from pathlib import Path

LOG = logging.getLogger("installer-payload")
ROOT = Path(__file__).resolve().parents[2]


def verify(compiler: Path):
    # 读取生产 Files 声明，避免测试另写一套排除规则。
    declaration = next(
        line for line in (ROOT / "installer/online.iss").read_text(encoding="utf-8").splitlines()
        if line.startswith('Source: "{#Payload}')
    )
    with tempfile.TemporaryDirectory(prefix="xuansi-payload-") as directory:
        check = Path(directory)
        payload = check / "payload"
        (payload / "pet").mkdir(parents=True)
        (payload / "web/frontend").mkdir(parents=True)
        (payload / "pet/desktop-entry.py").write_text("# 桌面运行入口\n", encoding="utf-8")
        (payload / "web/frontend/frontend-only.txt").write_text("官网专属文件", encoding="utf-8")
        source = declaration.replace("{#Payload}", str(payload))
        script = check / "verify.iss"
        script.write_text(
            "[Setup]\nAppName=Xuansi Payload Verification\nAppVersion=0.0.0\n"
            "DefaultDirName={tmp}\\XuansiVerification\nUninstallable=no\n"
            f"OutputDir={check}\nOutputBaseFilename=payload-verification\n"
            "Compression=none\n[Files]\n" + source + "\n",
            encoding="utf-8-sig",
        )
        result = subprocess.run([str(compiler), str(script)], capture_output=True, timeout=60)
        output = result.stdout.decode("utf-8", errors="replace")
        if result.returncode or "desktop-entry.py" not in output or "frontend-only.txt" in output:
            raise RuntimeError("Inno 载荷验证失败：编译输出未满足桌面保留/网站排除")
        LOG.info("真实编译通过：保留桌面入口，官网文件未进入安装载荷")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    verify(parser.parse_args().compiler.resolve(strict=True))
