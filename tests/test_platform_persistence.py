"""普通配置和平台字段共享持久化队列，拒绝旧快照覆盖与临时文件竞态。"""

import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pet.config import Settings, load_settings, save_settings
from pet.runtime import Runtime


@pytest.mark.parametrize("platform_first", [False, True])
def test_concurrent_settings_merge_latest_platform_fields(tmp_path, monkeypatch, platform_first):
    path = tmp_path / "settings.json"
    entered, release = threading.Event(), threading.Event()
    writes = []
    active = 0
    maximum = 0

    def write(settings):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if not writes:
            entered.set()
            assert release.wait(5)
        save_settings(settings, path)
        writes.append(settings)
        active -= 1

    monkeypatch.setattr("pet.runtime.save_settings", write)
    baseline = Settings()
    model_id = str(uuid4())
    events = []

    async def run():
        tasks = []
        def schedule(coroutine):
            task = asyncio.create_task(coroutine)
            tasks.append(task)
            return task
        runtime = SimpleNamespace(current_settings=baseline, storage_control=asyncio.Lock(), schedule=schedule,
                                  settings_saved=SimpleNamespace(emit=lambda *args: events.append(args)),
                                  platform_settings_saved=SimpleNamespace(emit=lambda *args: events.append(args)))
        ordinary = replace(baseline, name="新的本地名字", temperature=0.3)
        changes = {"platform_url": "https://example.org", "platform_model_version": model_id,
                   "avatar_image": ""}
        if platform_first:
            Runtime.persist_platform(runtime, changes)
        else:
            Runtime.persist(runtime, ordinary, validate_models=False)
        assert await asyncio.to_thread(entered.wait, 2)
        if platform_first:
            Runtime.persist(runtime, ordinary, validate_models=False)
        else:
            Runtime.persist_platform(runtime, changes)
        await asyncio.sleep(0)
        assert maximum == 1 and not writes
        release.set()
        await asyncio.gather(*tasks)
        assert runtime.current_settings.name == "新的本地名字"
        assert runtime.current_settings.platform_model_version == model_id

    try:
        asyncio.run(run())
    finally:
        release.set()
    stored = load_settings(path)
    assert stored.name == "新的本地名字" and stored.temperature == 0.3
    assert stored.platform_model_version == model_id and stored.platform_url == "https://example.org"
    assert maximum == 1 and len(writes) == 2
    assert all(error == "" for _, error in events)
    assert not path.with_suffix(".tmp").exists()


def test_external_model_never_advertises_xuansi_blink():
    from pet.avatar_motion import AvatarMotion

    owner = SimpleNamespace(_live2d_active=True, _live2d_model=object(),
                            _live2d_parameter_ids={"ParamEyeLOpen", "ParamEyeROpen"},
                            _platform_model_version=str(uuid4()))
    assert AvatarMotion.available_motions.fget(owner) == ()
