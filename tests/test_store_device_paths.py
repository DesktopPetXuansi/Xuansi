"""设备检查必须测量实际存放运行资源的磁盘。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from pet import config, inference
from pet.ai import device
from pet.ai_tasks import ProbeDevice


def test_settings_device_check_uses_writable_directory(monkeypatch, tmp_path):
    writable = tmp_path / "可写目录"
    model_dir = tmp_path / "模型目录"
    report = object()
    probe = Mock(return_value=report)
    signals = SimpleNamespace(device=SimpleNamespace(emit=Mock()))
    monkeypatch.setattr(config, "WRITABLE_ROOT", writable)
    monkeypatch.setattr(device, "probe_device", probe)

    ProbeDevice(signals, 3, model_dir).run()

    probe.assert_called_once_with(writable, model_dir)
    signals.device.emit.assert_called_once_with(3, report, "")


def test_local_engine_resource_check_uses_writable_directory(monkeypatch, tmp_path):
    writable = tmp_path / "可写目录"
    model = tmp_path / "模型.gguf"
    model.write_bytes(b"test")
    report = SimpleNamespace(avx2=True, gpus=[], memory_available=None)
    probe = Mock(return_value=report)
    monkeypatch.setattr(inference, "WRITABLE_ROOT", writable, raising=False)
    monkeypatch.setattr(device, "probe_device", probe)
    settings = config.Settings(model_path=str(model), projector_path=str(model))

    asyncio.run(inference.LocalEngine()._check_resources(settings, "cpu"))

    probe.assert_called_once_with(writable, tmp_path)
