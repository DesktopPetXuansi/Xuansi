"""只分类本实例引擎的资源错误；原始诊断不得进入应用日志。"""

import asyncio
from types import SimpleNamespace

import pytest

from pet.inference import LocalEngine


@pytest.mark.parametrize('requested,gpu_layers,installed,expected', [
    ('auto', 99, ('cpu',), 'cpu'),
    ('auto', 99, ('cpu', 'cuda'), 'cuda'),
    ('cuda', 99, ('cpu',), None),
    ('cpu', 99, ('cuda',), None),
    ('auto', 0, ('cpu', 'cuda'), 'cpu'),
])
def test_backend_uses_only_prepared_allowed_resources(tmp_path, requested, gpu_layers, installed, expected):
    """自动可使用已装 CPU；手选后端不能悄悄改用另一目录。"""
    from pet.inference import _local_executable

    for backend in installed:
        executable = tmp_path / backend / 'llama-server.exe'
        executable.parent.mkdir()
        executable.write_bytes(b'synthetic executable')
    backend, executable = _local_executable(tmp_path, requested, gpu_layers)
    if expected is None:
        assert executable is None
    else:
        assert backend == expected
        assert executable == tmp_path / expected / 'llama-server.exe'


def test_legacy_engine_directory_remains_supported(tmp_path):
    """单目录旧 CUDA 安装继续使用，不要求迁移或重新下载。"""
    from pet.inference import _local_executable

    executable = tmp_path / 'llama-b10930' / 'llama-server.exe'
    executable.parent.mkdir()
    executable.write_bytes(b'synthetic executable')
    assert _local_executable(tmp_path, 'auto', 99) == ('cuda', executable)


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['cpu', 'cuda'])
async def test_resource_precheck_counts_only_memory_available_to_selected_backend(tmp_path, monkeypatch, backend):
    """CPU 执行不能把独立显存误算为可用主内存。"""
    from pet.ai.providers.base import ProviderError

    model = tmp_path / 'synthetic.gguf'
    model.write_bytes(b'synthetic weights')
    settings = SimpleNamespace(model_path=str(model), projector_path=str(model))
    report = SimpleNamespace(avx2=True, memory_available=2**30,
                             gpus=(SimpleNamespace(memory_free=8 * 2**30),))
    monkeypatch.setattr('pet.ai.device.probe_device', lambda *_: report)
    if backend == 'cpu':
        with pytest.raises(ProviderError) as caught:
            await LocalEngine()._check_resources(settings, backend)
        assert caught.value.category == 'resource'
    else:
        await LocalEngine()._check_resources(settings, backend)


@pytest.mark.asyncio
@pytest.mark.parametrize('diagnostic,resource', [(b'CUDA error: out of memory', True),
                                               (b'ggml: failed to allocate buffer', True),
                                               (b'unsupported model architecture', False)])
async def test_owned_engine_diagnostics_classify_resources_without_logging_raw_text(caplog, diagnostic, resource):
    stream = asyncio.StreamReader()
    stream.feed_data(b'synthetic-private-marker\n' + diagnostic)
    stream.feed_eof()
    engine = LocalEngine()
    await engine._read_diagnostics(SimpleNamespace(stderr=stream))
    assert engine.resource_failure is resource
    assert 'synthetic-private-marker' not in caplog.text
