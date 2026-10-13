"""真实官网 API 验收入口：令牌只从 Windows 凭据管理器读取。"""

import asyncio
import json
import os

import pytest

from pet.platform_api import PlatformClient
from pet.platform_resources import read_installed


@pytest.mark.skipif(os.environ.get("PET_PLATFORM_API") != "1", reason="需已启动官网和浏览器授权")
def test_real_website_download_and_offline_verify(tmp_path):
    """设置测试资源 ID 即可验收真实清单/授权/下载，安装仅写 pytest 临时目录。"""
    base_url = os.environ.get("PET_PLATFORM_BASE_URL", "http://localhost:3000")
    versions = json.loads(os.environ["PET_PLATFORM_TEST_VERSIONS"])
    root = tmp_path / "resources"

    async def run():
        client = PlatformClient(base_url)
        assert client.store.read() is not None, "请先从桌宠资源库完成系统浏览器授权"
        library = await client.request("GET", "/me/library")
        assert isinstance(library, list)
        for version in versions:
            manifest = await client.install(version["resourceId"], version["resourceVersionId"], root)
            assert manifest["resourceVersionId"] == version["resourceVersionId"]
            assert read_installed(manifest["resourceVersionId"], root)[1].is_file()

    asyncio.run(run())
    # 离线阶段不使用 API 或令牌；逐项再次校验版本与文件摘要。
    for version in versions:
        manifest, path = read_installed(version["resourceVersionId"], root)
        assert manifest["resourceId"] == version["resourceId"] and path.is_file()
