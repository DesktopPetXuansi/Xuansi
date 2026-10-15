"""真实 Inno 编译验证：保留桌面及共享校验样例，排除官网程序。"""

import argparse
import logging
import subprocess
import tempfile
from pathlib import Path

LOG = logging.getLogger("installer-payload")
ROOT = Path(__file__).resolve().parents[2]


def verify(compiler: Path):
    # 读取生产 Files 声明，避免测试另写一套排除规则。
    declarations = [
        line for line in (ROOT / "installer/online.iss").read_text(encoding="utf-8").splitlines()
        if line.startswith('Source: "{#Payload}')
    ]
    with tempfile.TemporaryDirectory(prefix="xuansi-payload-") as directory:
        check = Path(directory)
        payload = check / "payload"
        (payload / "pet").mkdir(parents=True)
        (payload / "web/frontend").mkdir(parents=True)
        shared = payload / "web/contracts/fixtures/model-references.json"
        shared.parent.mkdir(parents=True)
        shared.write_bytes((ROOT / "web/contracts/fixtures/model-references.json").read_bytes())
        (payload / "pet/desktop-entry.py").write_text("# 桌面运行入口\n", encoding="utf-8")
        (payload / "web/frontend/frontend-only.txt").write_text("官网专属文件", encoding="utf-8")
        source = "\n".join(declarations).replace("{#Payload}", str(payload))
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
        if (result.returncode or "desktop-entry.py" not in output
                or "model-references.json" not in output or "frontend-only.txt" in output):
            raise RuntimeError("Inno 载荷验证失败：桌面入口/共享样例必须保留，官网程序必须排除")
        LOG.info("真实编译通过：保留桌面入口与共享样例，官网程序未进入安装载荷")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    verify(parser.parse_args().compiler.resolve(strict=True))
