"""Transfer fixed assets to a partial file and publish only verified bytes."""

import hashlib
import logging
import time
from http.client import HTTPException
from threading import Event
from urllib.request import Request, urlopen

LOG = logging.getLogger(__name__)


class DownloadPaused(Exception):
    pass


def fetch_resource(url, path, sha256, *, size=None, stop=None, report=None, partial_suffix=".part"):
    urls = (url,) if isinstance(url, str) else url
    stop = stop or Event()
    report = report or (lambda _phase, _bytes: None)

    def check_stop():
        if stop.is_set():
            raise DownloadPaused()

    def matches(file):
        report("verify", 0)
        digest = hashlib.sha256()
        with file.open("rb") as stream:
            while chunk := stream.read(4 * 1024 * 1024):
                check_stop()
                digest.update(chunk)
        return digest.hexdigest() == sha256

    check_stop()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and (size is None or path.stat().st_size == size) and matches(path):
        return
    partial = path.with_suffix(path.suffix + partial_suffix)
    for attempt in range(6):
        check_stop()
        offset = partial.stat().st_size if partial.is_file() else 0
        if size is not None and offset == size:
            if matches(partial):
                partial.replace(path)
                return
            partial.unlink()
            offset = 0
        headers = {"User-Agent": "DesktopPet-Local-Setup/1.0", "Accept-Encoding": "identity"}
        if offset and (size is None or offset < size):
            headers["Range"] = f"bytes={offset}-"
        else:
            offset = 0
        try:
            with urlopen(Request(urls[attempt % len(urls)], headers=headers), timeout=12) as response:
                if response.status == 200:
                    offset = 0
                elif response.status != 206 or not response.headers.get(
                        "Content-Range", "").startswith(f"bytes {offset}-"):
                    raise OSError("下载响应的续传位置不匹配")
                total = size if size is not None else offset + int(response.headers.get("Content-Length", "0"))
                started, current, reported = time.monotonic(), offset, 0
                report("download", current)
                with partial.open("ab" if offset else "wb") as stream:
                    while not stop.is_set() and (chunk := response.read(1024 * 1024)):
                        check_stop()
                        current += len(chunk)
                        if total and current > total:
                            raise ValueError("下载文件超过清单大小")
                        stream.write(chunk)
                        delay = (current - offset) / (2 * 1024 * 1024) - (time.monotonic() - started)
                        if delay > 0:
                            stop.wait(delay)
                        if time.monotonic() - reported >= 0.25:
                            report("download", current)
                            reported = time.monotonic()
            check_stop()
            if total and current != total:
                raise OSError("下载提前结束，继续断点续传")
            if not matches(partial):
                raise ValueError("下载文件校验失败")
            partial.replace(path)
            LOG.info("下载完成并校验 %s", path.name)
            return
        except (OSError, HTTPException) as exc:
            LOG.warning("下载 %s 第 %d 次失败：%s", path.name, attempt + 1, type(exc).__name__)
            if attempt < 5:
                stop.wait(min(attempt + 1, 5))
        except ValueError:
            partial.unlink(missing_ok=True)
            if len(urls) == 1 or attempt == 5:
                raise
    raise OSError("模型下载中断。请检查网络或磁盘后重试，已下载部分会保留。")
