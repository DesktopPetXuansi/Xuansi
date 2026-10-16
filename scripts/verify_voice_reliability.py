"""历史语音可靠性入口：转到原生工具完整套件；不覆盖 ASR、低音量识别或历史失败波形重放。

旧日期的验收报告仅代表旧协议，不能作为当前版本通过证据。
实际原生闭环由 verify_tool_dialogue.py 运行；报告另存新路径，明确保留覆盖边界。
"""

import argparse
import logging
import sys
from pathlib import Path

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/verification/voice-reliability-native-tools-report.json")
    parser.add_argument("--suite", choices=("smoke", "full", "speech"), default="full")
    parser.add_argument("--gpu-layers", type=int, default=99)
    parser.add_argument("--repro-audio", type=Path, help="已退役：旧 ASR 波形复验不属于新工具套件")
    arguments = parser.parse_args(argv)
    if arguments.repro_audio is not None:
        parser.error("--repro-audio 已退役；本入口不检查 ASR 或旧 NPZ 波形，不能用新报告替代历史识别验收。")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    LOG.warning("历史入口已迁移：%s", __doc__.splitlines()[0])
    # 延迟加载真实验收入口，使 --help 不启动模型或访问任何用户数据。
    from verify_tool_dialogue import main as verify_tools

    return verify_tools([
        "--suite", arguments.suite, "--output", str(arguments.output),
        "--gpu-layers", str(arguments.gpu_layers),
    ])


if __name__ == "__main__":
    sys.exit(main())
