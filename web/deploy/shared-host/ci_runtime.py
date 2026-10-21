"""仅操作玄司固定目录、服务和容器的主机端发布原语。"""

import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from ci_bundle import REPOSITORY


class Runtime:
    def __init__(self, root=Path("/opt/xuansi")):
        self.root = root
        self.nginx = Path("/srv/manga/nginx/conf.d/xuansi.kukude.top.conf")
        self.state_file = root / "shared/deployment-state.json"
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def event(self, message):
        print("[玄司部署] " + message, flush=True)

    def run(self, args, **kwargs):
        result = subprocess.run(args, capture_output=True, timeout=180, **kwargs)
        if result.returncode:
            # 原始诊断仅落服务器 root 私有文件，GitHub 日志只显示固定阶段。
            path = self.root / "shared/deploy-last-error.log"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(result.stderr[-8000:] + result.stdout[-8000:])
            raise RuntimeError("服务器命令失败：" + Path(args[0]).name)
        return result.stdout

    def assert_latest(self, commit):
        request = urllib.request.Request("https://api.github.com/repos/" + REPOSITORY + "/git/ref/heads/main",
            headers={"User-Agent": "Xuansi-production-deployer", "Accept": "application/vnd.github+json"})
        with self.http.open(request, timeout=20) as response:
            latest = json.load(response)["object"]["sha"]
        if latest != commit:
            raise ValueError("main 已有更新，拒绝用旧流水线覆盖线上版本")

    def get(self, port, path, expected=200):
        try:
            response = self.http.open(f"http://172.17.0.1:{port}{path}", timeout=5)
        except urllib.error.HTTPError as error:
            if error.code == expected:
                return b""
            raise
        with response:
            if response.status != expected:
                raise RuntimeError("内部 HTTP 检查未通过")
            return response.read(2 << 20)

    def wait_api(self):
        for attempt in range(30):
            try:
                if json.loads(self.get(18189, "/readyz"))["data"]["status"] == "ok":
                    self.get(18189, "/api/v1/auth/config")
                    self.get(18189, "/api/v1/resources")
                    self.get(18189, "/api/v1/me", 401)
                    return
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(1)
        raise RuntimeError("API 数据库就绪检查失败")

    def wait_frontend(self, port):
        for attempt in range(30):
            try:
                body = self.get(port, "/")
                if b"<html" in body:
                    break
            except OSError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("候选前端未就绪")
        for path in ("/download", "/login", "/resources", "/brand/icon.png",
                     "/_next/image?url=%2Fbrand%2Ficon.png&w=96&q=75"):
            self.get(port, path)

    def verify_public(self):
        # 公网验收放在事务内；失败时旧容器仍在，能够立即恢复应用入口。
        for path in ("/", "/download", "/resources", "/login", "/api/v1/auth/config"):
            for attempt in range(3):
                try:
                    request = urllib.request.Request("https://xuansi.kukude.top" + path,
                        headers={"User-Agent": "Xuansi-Deployment/1.0"})
                    with self.http.open(request, timeout=10) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                if attempt == 2:
                    raise RuntimeError("公网 HTTPS 健康检查失败：" + path)
                time.sleep(2)
        self.event("公网 HTTPS 页面与 API 检查通过")

    def snapshot(self):
        release = (self.root / "web-current").resolve(strict=True)
        if release.parent != (self.root / "releases").resolve():
            raise ValueError("当前发布链接不在玄司目录内")
        config = self.nginx.read_bytes()
        ports = re.findall(rb"proxy_pass http://172\.17\.0\.1:(1819[01]);", config)
        if len(ports) != 1:
            raise ValueError("前端上游配置不明确")
        port = int(ports[0])
        names = self.run(["docker", "ps", "--filter", "name=xuansi-frontend", "--format", "{{.Names}}"])
        for name in names.decode().splitlines():
            info = json.loads(self.run(["docker", "inspect", name]))[0]
            bindings = info["NetworkSettings"]["Ports"].get("3000/tcp") or []
            if any(b["HostIp"] == "172.17.0.1" and b["HostPort"] == str(port) for b in bindings):
                return dict(release=str(release), config=config, port=port, container=name)
        raise RuntimeError("找不到正在承接流量的玄司前端容器")

    def backup(self, name):
        folder = self.root / "backups" / name
        folder.mkdir(mode=0o700)
        fd = os.open(folder / "database.pgdump", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            result = subprocess.run(["docker", "exec", "-u", "postgres", "postgres1", "pg_dump",
                "-U", "postgres", "-Fc", "xuansi_feedback"], stdout=output, stderr=subprocess.PIPE, timeout=180)
        if result.returncode:
            raise RuntimeError("部署前数据库备份失败")
        with (folder / "database.pgdump").open("rb") as source:
            self.run(["docker", "exec", "-i", "postgres1", "pg_restore", "--list"], stdin=source)
        shutil.copyfile(self.nginx, folder / "nginx.conf")
        self.event("数据库备份及备份目录校验通过")

    def start_frontend(self, name, image, port):
        self.run(["docker", "run", "--detach", "--name", name, "--restart=unless-stopped",
            "--user=1000:1000", "--cap-drop=ALL", "--security-opt=no-new-privileges:true", "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m,mode=1777",
            "--tmpfs", "/app/.next/cache:rw,noexec,nosuid,size=32m,uid=1000,gid=1000,mode=0755",
            "--memory=256m", "--memory-swap=512m", "--cpus=1", "--pids-limit=128",
            "--env", "NODE_OPTIONS=--max-old-space-size=192", "--log-opt", "max-size=10m",
            "--log-opt", "max-file=3", "--publish", f"172.17.0.1:{port}:3000", image])

    def migrate(self, release):
        # EnvironmentFile 由 root 持有；秘密只传给普通应用进程，不进入命令行或 CI。
        environment = dict(os.environ)
        for line in (self.root / "shared/web.env").read_text("utf-8").splitlines():
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                environment[key] = json.loads(value)
        self.run([str(release / "api"), "-migrate-only"], env=environment,
            user="xuansi-web", group="xuansi-web", cwd=release)

    def link(self, release):
        pending = self.root / "web-current.pending"
        if pending.is_symlink():
            pending.unlink()
        pending.symlink_to(release)
        os.replace(pending, self.root / "web-current")

    def service(self, operation, service):
        if service not in ("xuansi-api", "xuansi-worker"):
            raise ValueError("拒绝操作其他项目的服务")
        self.run(["systemctl", operation, service])

    def proxy(self, config):
        self.nginx.write_bytes(config)
        self.run(["docker", "exec", "nginx", "nginx", "-t"])
        self.run(["docker", "exec", "nginx", "nginx", "-s", "reload"])

    def save_state(self, data):
        pending = self.state_file.with_suffix(".pending")
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
        os.replace(pending, self.state_file)
