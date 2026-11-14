"""Build a self-contained version ZIP from an explicit committed source snapshot."""

import argparse
import json
import shutil
import stat
import zipfile
from pathlib import Path
from uuid import uuid4

from scripts.stage_store_payload import stage_payload

NATIVE_IDS = ("llama-cpu", "llama-cuda", "cudart")


def native_runtime(source: Path, stage: Path, cache: Path):
    from pet.ai.resource_download import fetch_resource

    catalog = json.loads((source / "pet/ai/catalog.json").read_text(encoding="utf-8"))
    resources = {item["id"]: item for item in catalog["resources"]}
    cache.mkdir(parents=True, exist_ok=True)
    for identity in NATIVE_IDS:
        item = resources[identity]
        if item["location"] != "runtime" or item["archive"] != "zip":
            raise ValueError("运行时目录中包含不受支持的资源格式")
        archive_path = cache / item["path"]
        fetch_resource(item["url"], archive_path, item["sha256"], size=item["bytes"])
        backend = "cpu" if identity == "llama-cpu" else "cuda"
        destination = stage / "runtime/llama" / backend
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                if any(character in entry.filename for character in ("\\", ":", "\x00")):
                    raise ValueError("运行时压缩包路径越界")
                parts = Path(entry.filename).parts
                if not parts or any(part in (".", "..") for part in parts) or Path(entry.filename).is_absolute():
                    raise ValueError("运行时压缩包路径越界")
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError("运行时压缩包包含链接")
                target = destination.joinpath(*parts)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    with archive.open(entry) as reader, target.open("rb") as existing:
                        while chunk := reader.read(1024 * 1024):
                            if chunk != existing.read(len(chunk)):
                                raise ValueError("运行时压缩包包含冲突文件")
                        if existing.read(1):
                            raise ValueError("运行时压缩包包含冲突文件")
                    continue
                with archive.open(entry) as reader, target.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)


def build(source: Path, python_runtime: Path, dependencies: Path, cache: Path, output: Path):
    if output.exists():
        raise FileExistsError("更新包目标已存在")
    stage = output.with_name("." + output.stem + ".staging-" + uuid4().hex)
    stage_payload(source=source, python_runtime=python_runtime, dependencies=dependencies, output=stage)
    native_runtime(source, stage, cache)
    (stage / "store-payload.json").unlink()
    version = (stage / "VERSION").read_text(encoding="utf-8").strip()
    (stage / "update-bundle.json").write_text(
        json.dumps({"format": 1, "version": version, "native": list(NATIVE_IDS)}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as bundle:
        for file in sorted(stage.rglob("*")):
            if file.is_file():
                bundle.write(file, file.relative_to(stage).as_posix())
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "python-runtime", "dependencies", "cache", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.python_runtime, args.dependencies, args.cache, args.output)


if __name__ == "__main__":
    main()
