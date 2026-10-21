"""受限 SSH 入口：验证 main 产物，串行发布并在健康检查失败时恢复应用。"""

import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from ci_bundle import MAX_BUNDLE_BYTES, release_name, unpack_bundle
from ci_runtime import Runtime


def receive(stream, target):
    total = 0
    with target.open("xb") as output:
        while chunk := stream.read(1 << 20):
            total += len(chunk)
            if total > MAX_BUNDLE_BYTES:
                raise ValueError("上传发布包过大")
            output.write(chunk)
    if total == 0:
        raise ValueError("没有收到发布包；此密钥只能执行玄司部署协议")


def activate(runtime, release, old, container, port, commit):
    """候选前端先就绪；失败时恢复应用与代理，不自动回退数据库迁移。"""
    created = False
    changed = False
    try:
        runtime.start_frontend(container, "xuansi-frontend:ci-" + commit, port)
        created = True
        runtime.wait_frontend(port)
        runtime.assert_latest(commit)
        runtime.backup(release.name)
        changed = True
        runtime.service("stop", "xuansi-worker")
        runtime.migrate(release)
        runtime.link(release)
        runtime.service("restart", "xuansi-api")
        runtime.wait_api()
        runtime.service("start", "xuansi-worker")
        time.sleep(2)
        runtime.service("is-active", "xuansi-worker")
        config = old["config"].replace(
            f"http://172.17.0.1:{old['port']}".encode(), f"http://172.17.0.1:{port}".encode())
        runtime.proxy(config)
        runtime.wait_frontend(port)
        runtime.wait_api()
    except Exception:
        if not changed:
            if created:
                runtime.run(["docker", "rm", "--force", container])
            raise RuntimeError("候选检查未通过，当前线上版本保持运行")
        runtime.event("发布未通过，恢复上一版应用和代理")
        try:
            runtime.service("stop", "xuansi-worker")
            runtime.link(Path(old["release"]))
            runtime.service("restart", "xuansi-api")
            runtime.proxy(old["config"])
            runtime.service("start", "xuansi-worker")
            runtime.wait_api()
            runtime.wait_frontend(old["port"])
            runtime.run(["docker", "rm", "--force", container])
        except Exception as error:
            raise RuntimeError("应用恢复未通过健康检查，需要检查服务器；数据库备份保留") from error
        raise RuntimeError("发布失败，上一版应用已恢复；数据库未执行回退")


def deploy(runtime, stream, commit, run_id, attempt):
    runtime.assert_latest(commit)
    if runtime.state_file.exists():
        previous = json.loads(runtime.state_file.read_text("utf-8"))
        if (run_id, attempt) < (previous["run_id"], previous["attempt"]):
            raise ValueError("拒绝较旧的流水线覆盖已发布版本")
        if (run_id, attempt) == (previous["run_id"], previous["attempt"]):
            if previous["commit"] != commit:
                raise ValueError("流水线编号与已发布提交不匹配")
            runtime.wait_api()
            runtime.wait_frontend(previous["port"])
            runtime.event("此发布已完成且健康，无需重复切换")
            return
    with tempfile.TemporaryDirectory(prefix="ci-", dir=runtime.root / "shared") as scratch:
        scratch = Path(scratch)
        receive(stream, scratch / "bundle.tar.gz")
        manifest = unpack_bundle(scratch / "bundle.tar.gz", scratch / "payload")
        if (manifest["commit"], manifest["run_id"]) != (commit, run_id) or manifest["attempt"] > attempt:
            raise ValueError("SSH 请求与发布包身份不一致")
        # 仅重跑失败部署时复用同一运行已通过检查的产物，使用新的发布尝试编号。
        manifest["artifact_attempt"], manifest["attempt"] = manifest["attempt"], attempt
        runtime.assert_latest(commit)
        release = runtime.root / "releases" / release_name(manifest)
        if release.exists():
            raise ValueError("该发布目录已存在；重试请使用新的运行次数")
        release.mkdir(mode=0o755)
        for name in ("api", "worker", "admin", "release.json", "SHA256SUMS"):
            shutil.copyfile(scratch / "payload" / name, release / name)
            (release / name).chmod(0o755 if name in ("api", "worker", "admin") else 0o644)
        runtime.event("发布包身份和 SHA256 校验通过")
        runtime.run(["docker", "load", "--input", str(scratch / "payload/frontend-image.tar.gz")])
        old = runtime.snapshot()
        port = 18191 if old["port"] == 18190 else 18190
        container = "xuansi-frontend-ci-" + release.name.removeprefix("web-ci-")
        activate(runtime, release, old, container, port, commit)
        runtime.save_state(dict(manifest, release=str(release), port=port, container=container,
            previous_release=old["release"], previous_container=old["container"]))
        # 上一容器留作人工恢复，停止它即可释放内存及下次候选端口。
        runtime.run(["docker", "update", "--restart=no", old["container"]])
        runtime.run(["docker", "stop", "--time", "15", old["container"]])
        runtime.event("上线成功：" + commit)


def main():
    # authorized_keys 的 command 固定调用此入口；原始 SSH 命令只接受固定协议。
    command = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    match = re.fullmatch(r"deploy ([0-9a-f]{40}) ([1-9][0-9]{0,17}) ([1-9][0-9]{0,8})", command)
    if command != "status" and not match:
        print("此密钥仅允许网站发布和状态检查", file=sys.stderr)
        return 2
    if os.getuid() != 0:
        raise RuntimeError("发布入口必须由受限系统密钥调用")
    runtime = Runtime()
    import fcntl
    with (runtime.root / "shared/deployment.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if command == "status":
            snapshot = runtime.snapshot()
            revision = json.loads((Path(snapshot["release"]) / "release.json").read_text("utf-8"))["commit"]
            runtime.wait_api()
            runtime.wait_frontend(snapshot["port"])
            print(json.dumps(dict(commit=revision, healthy=True)))
            return 0
        deploy(runtime, sys.stdin.buffer, match[1], int(match[2]), int(match[3]))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # 不输出请求、环境文件或原始子进程响应。
        print("[玄司部署] " + str(error), file=sys.stderr)
        raise SystemExit(1)
