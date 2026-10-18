"""安装器等待边界：子检查超时即终止，不打印参数、环境或 API 正文。"""

import argparse
import logging
import subprocess
import sys

LOG = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command or not 0 < args.timeout <= 240:
        return 2
    try:
        # stdin 无管道则隐藏进程不会等待用户输入；Key 已经由短时环境传入。
        result = subprocess.run([sys.executable, "-X", "utf8", *args.command],
                                stdin=subprocess.DEVNULL, timeout=args.timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.returncode
    except subprocess.TimeoutExpired:
        LOG.error("安装前检查超时，已终止本次辅助进程")
        return 124
    except OSError:
        LOG.error("安装前辅助进程无法启动")
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
