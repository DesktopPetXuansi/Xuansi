"""发布边界回归：验证恶意归档、损坏产物、过期发布和应用恢复。"""

import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci_bundle import BUNDLE_FILES, release_name, unpack_bundle, validate_manifest
from ci_deploy import activate, deploy, receive
from ci_runtime import Runtime

COMMIT = "a" * 40
IMAGE = "xuansi-frontend:ci-" + COMMIT


def bundle(path, change=None, extra=None):
    image = io.BytesIO()
    with tarfile.open(fileobj=image, mode="w:gz") as archive:
        data = json.dumps([{"RepoTags": [IMAGE]}]).encode()
        member = tarfile.TarInfo("manifest.json")
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    elf = b"\x7fELF\x02" + bytes(13) + b"\x3e\x00" + bytes(44)
    data = dict(repository="DesktopPetXuansi/Xuansi", commit=COMMIT, run_id=12, attempt=1, image=IMAGE)
    files = {name: elf for name in ("api", "worker", "admin")}
    files.update({"frontend-image.tar.gz": image.getvalue(), "release.json": json.dumps(data).encode()})
    files["SHA256SUMS"] = "".join(hashlib.sha256(content).hexdigest() + "  " + name + "\n" for name, content in files.items()).encode()
    if change:
        change(files)
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        if extra:
            archive.addfile(extra)


class BundleTests(unittest.TestCase):
    def test_valid_bundle_preserves_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle(root / "bundle.tgz")
            data = unpack_bundle(root / "bundle.tgz", root / "out")
            self.assertEqual(data["commit"], COMMIT)
            self.assertEqual(release_name(data), "web-ci-12-1-aaaaaaaaaaaa")
            self.assertEqual({p.name for p in (root / "out").iterdir()}, BUNDLE_FILES)

    def test_tampered_binary_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle(root / "bundle.tgz", lambda files: files.update(api=b"tampered"))
            with self.assertRaisesRegex(ValueError, "SHA256"):
                unpack_bundle(root / "bundle.tgz", root / "out")

    def test_traversal_and_links_are_rejected(self):
        for name, kind in [("../outside", tarfile.REGTYPE), ("linked", tarfile.SYMTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                member = tarfile.TarInfo(name)
                member.type, member.linkname = kind, "/etc/passwd"
                bundle(root / "bundle.tgz", extra=member)
                with self.assertRaises(ValueError):
                    unpack_bundle(root / "bundle.tgz", root / "out")
                self.assertFalse((root / "outside").exists())

    def test_unexpected_image_cannot_replace_other_project(self):
        with self.assertRaisesRegex(ValueError, "镜像"):
            validate_manifest(dict(repository="DesktopPetXuansi/Xuansi", commit=COMMIT,
                run_id=12, attempt=1, image="postgres:16"))

    def test_empty_ssh_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "没有收到"):
                receive(io.BytesIO(), Path(folder) / "bundle")


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Mock(spec=Runtime)
        self.old = dict(release="/opt/xuansi/releases/previous", port=18190,
            container="xuansi-frontend-old", config=b"proxy_pass http://172.17.0.1:18190;")
        self.release = Path("/opt/xuansi/releases/new")

    @patch("ci_deploy.time.sleep")
    def test_success_checks_candidate_before_changing_live_services(self, sleep):
        activate(self.runtime, self.release, self.old, "candidate", 18191, COMMIT)
        calls = [call[0] for call in self.runtime.method_calls]
        self.assertLess(calls.index("wait_frontend"), calls.index("backup"))
        self.assertLess(calls.index("backup"), calls.index("migrate"))
        self.runtime.link.assert_called_once_with(self.release)
        self.runtime.proxy.assert_called_once_with(b"proxy_pass http://172.17.0.1:18191;")

    @patch("ci_deploy.time.sleep")
    def test_backend_failure_restores_previous_application_and_proxy(self, sleep):
        self.runtime.wait_api.side_effect = [RuntimeError("candidate unhealthy"), None]
        with self.assertRaisesRegex(RuntimeError, "上一版应用已恢复"):
            activate(self.runtime, self.release, self.old, "candidate", 18191, COMMIT)
        self.assertEqual([call.args[0] for call in self.runtime.link.call_args_list],
            [self.release, Path(self.old["release"])])
        self.runtime.proxy.assert_called_once_with(self.old["config"])
        self.runtime.service.assert_any_call("start", "xuansi-worker")

    def test_bad_candidate_leaves_running_services_untouched(self):
        self.runtime.wait_frontend.side_effect = RuntimeError("bad frontend")
        with self.assertRaisesRegex(RuntimeError, "当前线上版本保持"):
            activate(self.runtime, self.release, self.old, "candidate", 18191, COMMIT)
        self.runtime.service.assert_not_called()
        self.runtime.link.assert_not_called()

    @patch("ci_deploy.time.sleep")
    def test_public_health_failure_restores_previous_version(self, sleep):
        self.runtime.verify_public.side_effect = [RuntimeError("public unhealthy"), None]
        with self.assertRaisesRegex(RuntimeError, "上一版应用已恢复"):
            activate(self.runtime, self.release, self.old, "candidate", 18191, COMMIT)
        self.assertEqual(self.runtime.link.call_args_list[-1].args[0], Path(self.old["release"]))
        self.assertEqual(self.runtime.proxy.call_args_list[-1].args[0], self.old["config"])
        self.assertEqual(self.runtime.verify_public.call_count, 2)

    def test_stale_commit_is_rejected_before_receiving_a_package(self):
        self.runtime.assert_latest.side_effect = ValueError("main 已有更新")
        stream = Mock()
        with self.assertRaises(ValueError):
            deploy(self.runtime, stream, COMMIT, 12, 1)
        stream.read.assert_not_called()
        self.runtime.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
