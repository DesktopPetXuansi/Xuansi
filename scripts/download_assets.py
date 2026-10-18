"""下载公开权重与推理引擎：限速、断点续传、SHA256 校验后再启用。"""

import argparse
import binascii
import hashlib
import json
import logging
import sys
import tarfile
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pet.ai.install_plan import default_model_dir

MODELS = Path(default_model_dir())
RUNTIME = ROOT / "runtime"
LOG = logging.getLogger("download")
HF = "https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/3885219b6810b007914f3a7950a8d1b469d598a5/"
GH = "https://github.com/ggml-org/llama.cpp/releases/download/b10930/"
SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
ASSETS = [
    (
        HF + "Qwen3.5-9B-Q4_K_M.gguf",
        MODELS / "qwen3.5-9b/Qwen3.5-9B-Q4_K_M.gguf",
        "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8",
    ),
    (
        HF + "mmproj-F16.gguf",
        MODELS / "qwen3.5-9b/mmproj-F16.gguf",
        "f70dc3509053962b0d0d3ee8a7eacebf5d60aa560cad78254ae8698516ae029f",
    ),
    (
        GH + "llama-b10930-bin-win-cuda-12.4-x64.zip",
        RUNTIME / "llama.zip",
        "7d07deb817f7f380d1da119c76967d7ead0a4dbb02456c0edfda82a99122fed6",
    ),
    (
        GH + "cudart-llama-bin-win-cuda-12.4-x64.zip",
        RUNTIME / "cudart.zip",
        "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
    ),
    (
        SHERPA + "asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09.tar.bz2",
        MODELS / "sensevoice.tar.bz2",
        "7305f7905bfcf77fa0b39388a313f3da35c68d971661a65475b56fb2162c8e63",
    ),
    (
        SHERPA + "tts-models/kokoro-int8-multi-lang-v1_1.tar.bz2",
        MODELS / "kokoro.tar.bz2",
        "a1e94694776049035c4f2c6529f003aaece993c76aae9a78995831c3c4dcafc6",
    ),
    # 此历史发布包未提供作者 SHA；这里锁定首次 HTTPS 下载实际计算的摘要。
    (
        SHERPA + "tts-models/vits-melo-tts-zh_en.tar.bz2",
        MODELS / "melo.tar.bz2",
        "e58351ed7149f290a54534538badd4077cdbe6fddc964b24d0bee870415d1514",
    ),
]


def digest(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(asset: tuple[str, Path, str]):
    url, path, expected = asset
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and digest(path) == expected:
        LOG.info("已校验 %s", path.name)
        return
    partial = path.with_suffix(path.suffix + ".part")
    for attempt in range(6):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "DesktopPet-Local-Setup/1.0"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=25) as response:
                # 服务端不支持 Range 时从头开始，避免拼接出损坏的模型。
                if response.status != 206:
                    offset = 0
                elif not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise ValueError("续传起点不匹配")
                total = offset + int(response.headers.get("Content-Length", "0"))
                started, current, reported = time.monotonic(), offset, time.monotonic()
                LOG.info("下载 %s，%.1f / %.1f MiB", path.name, offset / 2**20, total / 2**20)
                with partial.open("ab" if offset else "wb") as stream:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
                        current += len(chunk)
                        # 每个任务最多 2MiB/s；三个并发避免占满用户网络。
                        delay = (current - offset) / (2 * 1024 * 1024) - (time.monotonic() - started)
                        if delay > 0:
                            time.sleep(delay)
                        if time.monotonic() - reported > 30:
                            LOG.info("进度 %s %.1f%%", path.name, current / max(total, 1) * 100)
                            reported = time.monotonic()
            if total and partial.stat().st_size < total:
                raise OSError("下载提前结束，继续断点续传")
            if digest(partial) != expected:
                raise ValueError("SHA256 不匹配，拒绝启用")
            partial.replace(path)
            LOG.info("完成并校验 %s", path.name)
            return
        except Exception as exc:
            LOG.warning("%s 第 %d 次失败：%s", path.name, attempt + 1, type(exc).__name__)
            if isinstance(exc, ValueError):
                raise
            time.sleep(min(attempt + 1, 5))
    raise RuntimeError(f"下载失败：{path.name}，保留续传文件")


def extract(assets=None, models=MODELS, runtime=RUNTIME, manifest_path=None):
    """只解压本次选择的资源，不要求其他模型或语音包存在。"""
    destination = runtime / "llama"
    selected = ASSETS if assets is None else assets
    for _, path, _ in selected:
        if path.suffix != ".zip":
            continue
        backend = "cuda" if path.name in ("llama.zip", "cudart.zip") else "cpu"
        destination = runtime / "llama" / backend
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                target = (destination / entry.filename).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise ValueError("发布包路径越界")
                if target.is_file() and target.stat().st_size == entry.file_size:
                    with target.open("rb") as current:
                        checksum = 0
                        while chunk := current.read(1024 * 1024):
                            checksum = binascii.crc32(chunk, checksum)
                    if checksum == entry.CRC:
                        continue
                archive.extract(entry, destination)
    for _, path, _ in selected:
        if not path.name.endswith(".tar.bz2"):
            continue
        with tarfile.open(path) as archive:
            archive.extractall(models, filter="data")
    manifest = [
        {"url": url, "filename": path.name, "sha256": checksum, "bytes": path.stat().st_size}
        for url, path, checksum in selected
    ]
    (manifest_path or ROOT / "assets-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    LOG.info("解压和清单完成")


def deploy_plan(plan):
    """固定目录推导路径，使用有界并发及既有续传和完整摘要校验。"""
    from pet.ai.install_plan import default_model_dir, resources_for

    app = Path(plan.app_dir) if plan.app_dir else ROOT
    models = Path(plan.model_dir or default_model_dir())
    runtime = app / "runtime"
    assets = [(item.url, (runtime if item.location == "runtime" else models) / item.path, item.sha256)
              for item in resources_for(plan)]
    if not assets:
        LOG.info("本次未选择本地模型或语音资源，跳过下载")
        return
    app.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(fetch, assets))
    extract(assets, models, runtime, app / "assets-manifest.json")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    if args.plan:
        sys.path.insert(0, str(ROOT))
        from pet.ai.install_plan import load_plan

        deploy_plan(load_plan(args.plan))
        return
    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(fetch, ASSETS))
    extract()


if __name__ == "__main__":
    main()
