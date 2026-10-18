"""从已锁版本的纯 Python 依赖组装安装前 bundle，不联网、不运行 pip。"""

import argparse
import importlib.metadata
import importlib.util
import logging
import shutil
from pathlib import Path

LOG = logging.getLogger(__name__)
PACKAGES = ("httpx", "httpcore", "anyio", "h11", "certifi", "idna", "typing_extensions")


def build_bundle(destination: Path, lock: Path):
    locked = dict(line.strip().split("==", 1) for line in lock.read_text(encoding="utf-8-sig").splitlines()
                  if "==" in line and not line.lstrip().startswith("#"))
    destination.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name in PACKAGES:
        version = importlib.metadata.version(name)
        if locked.get(name) != version:
            raise ValueError(f"安装前依赖版本与锁文件不一致：{name}")
        module = importlib.util.find_spec(name)
        if module is None or module.origin is None:
            raise ValueError(f"安装前依赖不存在：{name}")
        source = Path(module.origin)
        if source.name == "__init__.py":
            shutil.copytree(source.parent, destination / name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(source, destination / source.name)
        # 将发行许可随包放入临时 bundle 与正式 payload，避免只复制代码漏许可。
        distribution = importlib.metadata.distribution(name)
        for item in distribution.files or ():
            if ".dist-info/" in str(item).replace("\\", "/"):
                path = Path(distribution.locate_file(item))
                if path.is_file():
                    target = destination / str(item)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
        manifest.append(f"{name}=={version}")
    (destination / "preflight-dependencies.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    LOG.info("前置 HTTP 依赖 bundle 已组装，固定依赖数=%d", len(manifest))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    build_bundle(arguments.output, arguments.lock)
