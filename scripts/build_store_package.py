"""将已暂存的桌面载荷打成未签名 MSIX；不安装、不签名，也不提交商店。"""

import argparse
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PureWindowsPath
from xml.etree import ElementTree as ET

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
NS = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
UAP = "http://schemas.microsoft.com/appx/manifest/uap/windows10"
RESCAP = "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
ET.register_namespace("", NS)
ET.register_namespace("uap", UAP)
ET.register_namespace("rescap", RESCAP)


def _relative_file(payload, value, extension):
    path = PureWindowsPath(value)
    if (not value or path.drive or path.root or ".." in path.parts
            or any(char in value for char in '<>:"|?*\r\n')
            or any(part.endswith((" ", ".")) for part in path.parts)
            or path.suffix.lower() != extension):
        raise ValueError("入口与图标必须是载荷内的规范相对路径")
    target = payload.joinpath(*path.parts)
    if not target.is_file() or not target.resolve().is_relative_to(payload):
        raise FileNotFoundError("入口或图标不存在于暂存载荷中")
    return str(path)


def _payload_files(payload):
    def unreadable(error):
        raise error  # 目录不可读时停止，避免静默生成缺少依赖的包。

    files = []
    forbidden = {"data", "models", ".git", ".venv", "appxmanifest.xml", "appxblockmap.xml",
                 "appxsignature.p7x", "[content_types].xml"}
    for current, directories, filenames in os.walk(payload, followlinks=False, onerror=unreadable):
        for name in sorted([*directories, *filenames]):
            path = Path(current) / name
            relative = path.relative_to(payload)
            if (path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(payload)
                    or any(char in str(path) for char in '"\r\n')):
                raise ValueError("载荷不能包含链接、外部路径或不可映射的文件名")
            if relative.parts[0].casefold() in forbidden or relative.parts[0].casefold().startswith(".env"):
                raise ValueError("载荷包含用户数据、开发环境或已有包元数据，请先单独暂存")
            if path.is_file():
                files.append((path, str(PureWindowsPath(*relative.parts))))
            elif not path.is_dir():
                raise ValueError("载荷只能包含普通文件与目录")
    if not files:
        raise ValueError("载荷为空")
    return sorted(files, key=lambda item: item[1])


def _manifest(identity, publisher, publisher_display_name, version, executable,
              display_name, store_logo, small_logo, large_logo):
    if not re.fullmatch(r"[A-Za-z0-9.-]{3,50}", identity) or identity.endswith("."):
        raise ValueError("包标识必须使用 Partner Center 的有效 Name")
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.0", version):
        raise ValueError("商店包版本必须是四段数字，最后一段保留为 0")
    parts = [int(part) for part in version.split(".")]
    if parts[0] == 0 or any(part > 65535 for part in parts):
        raise ValueError("商店包版本各段必须在允许范围内")
    if not publisher.startswith("CN="):
        raise ValueError("发布者必须使用 Partner Center 的 Publisher")
    for text in (publisher, publisher_display_name, display_name):
        if not text.strip() or len(text) > 256 or any(ord(char) < 32 for char in text):
            raise ValueError("发布者和显示名称不能为空或包含控制字符")
    package = ET.Element(f"{{{NS}}}Package", IgnorableNamespaces="uap rescap")
    ET.SubElement(package, f"{{{NS}}}Identity", Name=identity, Publisher=publisher,
                  Version=version, ProcessorArchitecture="x64")
    properties = ET.SubElement(package, f"{{{NS}}}Properties")
    for name, value in (("DisplayName", display_name), ("PublisherDisplayName", publisher_display_name),
                        ("Description", "玄司 AI 桌面伙伴"), ("Logo", store_logo)):
        ET.SubElement(properties, f"{{{NS}}}{name}").text = value
    ET.SubElement(ET.SubElement(package, f"{{{NS}}}Resources"), f"{{{NS}}}Resource", Language="zh-CN")
    ET.SubElement(ET.SubElement(package, f"{{{NS}}}Dependencies"), f"{{{NS}}}TargetDeviceFamily",
                  Name="Windows.Desktop", MinVersion="10.0.17763.0", MaxVersionTested="10.0.26200.0")
    application = ET.SubElement(ET.SubElement(package, f"{{{NS}}}Applications"), f"{{{NS}}}Application",
                                Id="Xuansi", Executable=executable, EntryPoint="Windows.FullTrustApplication")
    ET.SubElement(application, f"{{{UAP}}}VisualElements", DisplayName=display_name,
                  Description="玄司 AI 桌面伙伴", Square150x150Logo=large_logo,
                  Square44x44Logo=small_logo, BackgroundColor="transparent")
    ET.SubElement(ET.SubElement(package, f"{{{NS}}}Capabilities"), f"{{{RESCAP}}}Capability", Name="runFullTrust")
    return ET.ElementTree(package)


def build_package(*, payload: Path, output: Path, makeappx: Path, identity: str, publisher: str,
                  publisher_display_name: str, version: str, executable: str, display_name: str,
                  store_logo: str, small_logo: str, large_logo: str):
    if payload.is_symlink() or payload.is_junction():
        raise ValueError("暂存载荷根目录不能是链接")
    if output.exists() or output.is_symlink() or output.is_junction():
        raise FileExistsError("输出文件已存在，保留原产物")
    payload, output, makeappx = payload.resolve(), output.resolve(), makeappx.resolve()
    if not payload.is_dir():
        raise FileNotFoundError("暂存载荷目录不存在")
    if output.suffix.lower() != ".msix" or output.is_relative_to(payload):
        raise ValueError("输出必须是载荷目录外的 MSIX 文件")
    if output.is_relative_to(ROOT) and not any(output.is_relative_to(ROOT / name) for name in ("build", "dist")):
        raise ValueError("仓库内产物仅允许写入 build 或 dist")
    if output.exists():
        raise FileExistsError("输出文件已存在，保留原产物")
    files = _payload_files(payload)
    paths = [_relative_file(payload, value, suffix) for value, suffix in
             ((executable, ".exe"), (store_logo, ".png"), (small_logo, ".png"), (large_logo, ".png"))]
    manifest = _manifest(identity, publisher, publisher_display_name, version, paths[0], display_name, *paths[1:])
    if not makeappx.is_file():
        raise FileNotFoundError("请显式提供 Windows SDK 的 MakeAppx.exe")

    # 映射只引用已检查的载荷，不复制开发目录，也不修改输入文件。
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".xuansi-msix-", dir=output.parent)).resolve()
    try:
        manifest_path = temporary / "AppxManifest.xml"
        manifest.write(manifest_path, encoding="utf-8", xml_declaration=True)
        mapping = temporary / "mapping.txt"
        entries = [(manifest_path, "AppxManifest.xml"), *files]
        mapping.write_text("[Files]\n" + "\n".join(f'"{source}" "{target}"' for source, target in entries),
                           encoding="utf-8")
        staged = temporary / "package.msix"
        result = subprocess.run([str(makeappx), "pack", "/f", str(mapping), "/p", str(staged), "/h", "SHA256", "/no"],
                                capture_output=True, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0 or not staged.is_file():
            raise RuntimeError(f"MakeAppx 构建失败，退出码 {result.returncode}")
        # Windows 的同卷重命名不覆盖已有目标，也不留下需清理的大型硬链接。
        if os.name == "nt":
            os.rename(staged, output)
        else:
            # 其他系统的 rename 可能覆盖目标，使用独占硬链接保护既有产物。
            os.link(staged, output)
        LOG.info("未签名 MSIX 容器已生成，载荷文件数=%d；尚未验证安装与商店审核", len(files))
    finally:
        # 递归清理前重新确认目标仍为本次在输出目录创建的临时目录。
        if (temporary.resolve().parent != output.parent or not temporary.name.startswith(".xuansi-msix-")
                or temporary.is_symlink() or temporary.is_junction()):
            raise RuntimeError("临时构建目录身份改变，停止自动清理")
        shutil.rmtree(temporary)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("payload", "output", "makeappx"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("identity", "publisher", "publisher-display-name", "version", "executable", "display-name",
                 "store-logo", "small-logo", "large-logo"):
        parser.add_argument("--" + name, required=True)
    arguments = parser.parse_args()
    try:
        build_package(**vars(arguments))
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        LOG.error("MSIX 容器构建未完成，类别=%s", type(error).__name__)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
