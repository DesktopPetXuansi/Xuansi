"""把已通过检查的 Linux 程序和前端镜像封装为有摘要的发布包。"""

import argparse
import io
import json
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/shared-host"))
from ci_bundle import PAYLOAD_FILES, REPOSITORY, digest, validate_manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binaries", type=Path, required=True)
    parser.add_argument("--image-archive", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = validate_manifest(dict(repository=REPOSITORY, commit=args.commit,
        run_id=args.run_id, attempt=args.attempt, image="xuansi-frontend:ci-" + args.commit))
    with tempfile.TemporaryDirectory() as scratch:
        metadata = Path(scratch) / "release.json"
        metadata.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        files = {name: args.binaries / name for name in ("api", "worker", "admin")}
        files.update({"frontend-image.tar.gz": args.image_archive, "release.json": metadata})
        assert set(files) == PAYLOAD_FILES
        sums = "".join(digest(files[name]) + "  " + name + "\n" for name in sorted(files)).encode()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(args.output, "w:gz", compresslevel=1) as archive:
            for name, path in files.items():
                info = archive.gettarinfo(str(path), arcname=name)
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ""
                info.mode = 0o600
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
            info = tarfile.TarInfo("SHA256SUMS")
            info.size, info.mode = len(sums), 0o600
            archive.addfile(info, io.BytesIO(sums))
    print("已生成并附带 SHA256 的网站发布包：" + args.output.name)


if __name__ == "__main__":
    main()
