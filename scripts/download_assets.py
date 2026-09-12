"""下载公开权重与推理引擎：限速、断点续传、SHA256 校验后再启用。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import logging
import tarfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODELS = Path('D:/AI/Models/desktop-pet')
RUNTIME = ROOT / 'runtime'
LOG = logging.getLogger('download')
HF = 'https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/'
GH = 'https://github.com/ggml-org/llama.cpp/releases/download/b10930/'
SHERPA = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/'
ASSETS = [
    (HF+'Qwen3.5-4B-Q4_K_M.gguf', MODELS/'Qwen3.5-4B-Q4_K_M.gguf', '00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4'),
    (HF+'mmproj-F16.gguf', MODELS/'mmproj-F16.gguf', 'cd88edcf8d031894960bb0c9c5b9b7e1fea6ebee02b9f7ce925a00d12891f864'),
    (GH+'llama-b10930-bin-win-cuda-12.4-x64.zip', RUNTIME/'llama.zip', '7d07deb817f7f380d1da119c76967d7ead0a4dbb02456c0edfda82a99122fed6'),
    (GH+'cudart-llama-bin-win-cuda-12.4-x64.zip', RUNTIME/'cudart.zip', '8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6'),
    (SHERPA+'asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09.tar.bz2', MODELS/'sensevoice.tar.bz2', '7305f7905bfcf77fa0b39388a313f3da35c68d971661a65475b56fb2162c8e63'),
    (SHERPA+'tts-models/kokoro-int8-multi-lang-v1_1.tar.bz2', MODELS/'kokoro.tar.bz2', 'a1e94694776049035c4f2c6529f003aaece993c76aae9a78995831c3c4dcafc6'),
]


def digest(path: Path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch(asset: tuple[str, Path, str]):
    url, path, expected = asset
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and digest(path) == expected:
        LOG.info('已校验 %s', path.name)
        return
    partial = path.with_suffix(path.suffix+'.part')
    for attempt in range(6):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {'User-Agent': 'DesktopPet-Local-Setup/1.0'}
        if offset:
            headers['Range'] = f'bytes={offset}-'
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=25) as response:
                # 服务端不支持 Range 时从头开始，避免拼接出损坏的模型。
                if response.status != 206:
                    offset = 0
                elif not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                    raise ValueError('续传起点不匹配')
                total = offset + int(response.headers.get('Content-Length', '0'))
                started, current, reported = time.monotonic(), offset, time.monotonic()
                LOG.info('下载 %s，%.1f / %.1f MiB', path.name, offset/2**20, total/2**20)
                with partial.open('ab' if offset else 'wb') as stream:
                    while chunk := response.read(1024*1024):
                        stream.write(chunk)
                        current += len(chunk)
                        # 每个任务最多 2MiB/s；三个并发避免占满用户网络。
                        delay = (current-offset)/(2*1024*1024) - (time.monotonic()-started)
                        if delay > 0:
                            time.sleep(delay)
                        if time.monotonic()-reported > 30:
                            LOG.info('进度 %s %.1f%%', path.name, current/max(total, 1)*100)
                            reported = time.monotonic()
            if digest(partial) != expected:
                raise ValueError('SHA256 不匹配，拒绝启用')
            partial.replace(path)
            LOG.info('完成并校验 %s', path.name)
            return
        except Exception as exc:
            LOG.warning('%s 第 %d 次失败：%s', path.name, attempt+1, type(exc).__name__)
            if isinstance(exc, ValueError):
                raise
            time.sleep(min(attempt+1, 5))
    raise RuntimeError(f'下载失败：{path.name}，保留续传文件')


def extract():
    destination = RUNTIME/'llama'
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('llama.zip', 'cudart.zip'):
        with zipfile.ZipFile(RUNTIME/name) as archive:
            for entry in archive.infolist():
                if not (destination/entry.filename).resolve().is_relative_to(destination.resolve()):
                    raise ValueError('发布包路径越界')
            archive.extractall(destination)
    for name in ('sensevoice.tar.bz2', 'kokoro.tar.bz2'):
        with tarfile.open(MODELS/name) as archive:
            archive.extractall(MODELS, filter='data')
    manifest = [{'url':url, 'filename':path.name, 'sha256':checksum, 'bytes':path.stat().st_size}
                for url,path,checksum in ASSETS]
    (ROOT/'assets-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    LOG.info('解压和清单完成')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(fetch, ASSETS))
    extract()
