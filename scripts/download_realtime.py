"""只增量下载实时识别权重；固定上游版本、校验摘要，不上传任何音频。"""

import logging
from concurrent.futures import ThreadPoolExecutor

from download_assets import MODELS, fetch

BASE = (
    "https://huggingface.co/csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en/resolve/"
    "8e40c43232a1c5c66c82111efc5820d3accca11b/"
)
ASSETS = [
    (BASE + name, MODELS / "streaming-paraformer" / name, checksum)
    for name, checksum in (
        ("encoder.int8.onnx", "81a70226a8934e6ed92aa1d4fc486b428b5398e2f2619ed4897b7294cab90e9a"),
        ("decoder.int8.onnx", "f3cca9f77bb9d93c8fcbfb63ae617b6b1ee96818df3aa3b151c40658fe38594f"),
        ("tokens.txt", "59aba8873a2ed1e122c25fee421e25f283b63290efbde85c1f01a853d83cb6e6"),
    )
]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(fetch, ASSETS))
