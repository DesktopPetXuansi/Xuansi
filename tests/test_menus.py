"""配置、日志和热键边界：使用临时文件及 Win32 替身，不修改用户设置。"""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from pet.config import Settings, load_settings
from pet.hotkey import GlobalHotkey, parse_hotkey
from pet.inference import LocalEngine
from pet.log_viewer import read_tail


def test_old_settings_use_new_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"name":"旧伙伴"}', encoding="utf-8")
    settings = load_settings(path)
    assert settings.name == "旧伙伴"
    assert settings.chat_hotkey == "Ctrl+Alt+Space"
    assert settings.temperature == 0.7


@pytest.mark.parametrize(
    "changes",
    [
        {"temperature": float("nan")},
        {"top_p": 0.0},
        {"max_tokens": 0},
        {"context_size": 999999},
        {"cpu_threads": 32},
        {"chat_hotkey": "Ctrl+C"},
    ],
)
def test_invalid_configuration_rejected(changes):
    with pytest.raises(ValueError):
        replace(Settings(), **changes).validate()


@pytest.mark.asyncio
async def test_sampling_parameters_reach_request():
    captured = []

    async def response(request):
        data = json.loads(request.content)
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        captured.append(data)
        return httpx.Response(200, json={"choices": [{"message": {"content": "参数测试"}}]})

    engine = LocalEngine()

    async def start(_):
        pass

    engine.start = start
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="http://127.0.0.1"
    ) as client:
        engine.client = client
        await engine.chat(replace(Settings(), temperature=0.2, top_p=0.5, max_tokens=320), "测试", [], [])
    assert (captured[0]["temperature"], captured[0]["top_p"], captured[0]["max_tokens"]) == (0.2, 0.5, 320)


def test_log_tail_bounded_and_rotation_reopened(tmp_path):
    path = tmp_path / "pet.log"
    path.write_text("测试 INFO 第一次\n" * 5000, encoding="utf-8")
    lines, error = read_tail(path, limit=1000)
    assert not error and len(lines) < 100
    assert all(line == "测试 INFO 第一次" for line in lines)
    path.rename(path.with_suffix(".log.1"))
    path.write_text("测试 WARNING 第二次\n", encoding="utf-8")
    assert read_tail(path)[0] == ["测试 WARNING 第二次"]


def test_hotkey_conflict_and_failed_save_keep_old_binding(monkeypatch):
    registered = {}

    def register(_, identifier, modifiers, code):
        if code == ord("X"):
            return False
        registered[identifier] = (modifiers, code)
        return True

    monkeypatch.setattr("pet.hotkey.USER32.RegisterHotKey", register)
    monkeypatch.setattr("pet.hotkey.USER32.UnregisterHotKey", lambda _, key: registered.pop(key))
    app = SimpleNamespace(installNativeEventFilter=lambda _: None, removeNativeEventFilter=lambda _: None)
    binding = GlobalHotkey(app, lambda: None)
    binding.stage("Ctrl+Alt+Space")
    binding.commit()
    original = binding.active
    with pytest.raises(ValueError, match="占用"):
        binding.stage("Ctrl+Alt+X")
    assert binding.active == original and len(registered) == 1
    binding.stage("Ctrl+Alt+Q")
    binding.rollback()  # 磁盘保存失败。
    assert binding.active == original and len(registered) == 1
    binding.stage("Ctrl+Alt+Q")
    binding.commit()
    assert binding.active != original and len(registered) == 1
    binding.close()
    assert not registered


def test_hotkey_parsing_prevents_single_keys_and_reserved_key():
    assert parse_hotkey("Ctrl+Alt+Space") == (0x4003, 0x20)
    for sequence in ("A", "Ctrl+C", "Ctrl+Ctrl+A", "Ctrl+Alt+F12", "Ctrl+Alt+Q, Ctrl+Q"):
        with pytest.raises(ValueError):
            parse_hotkey(sequence)


@pytest.mark.asyncio
async def test_context_and_threads_reach_engine_start_and_trigger_reload(monkeypatch):
    launches = []

    class Process:
        pid = 12345
        returncode = None

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    class Client:
        async def get(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=200)

        async def aclose(self):
            pass

    async def launch(*args, **_kwargs):
        launches.append(args)
        return Process()

    monkeypatch.setattr("pet.inference.asyncio.create_subprocess_exec", launch)
    monkeypatch.setattr("pet.inference.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setattr(
        "pet.inference.ProcessGuard", lambda: SimpleNamespace(attach=lambda _: None, close=lambda: None)
    )
    monkeypatch.setattr("pet.inference.Path.is_file", lambda _: True)
    monkeypatch.setattr(
        "pet.inference.Path.rglob", lambda *_: iter([Path("fake-server.exe")])
    )
    engine = LocalEngine()
    settings = replace(Settings(), context_size=8192, cpu_threads=2, gpu_layers=7)
    try:
        await engine.start(settings)
        args = launches[0]
        assert [args[args.index(flag) + 1] for flag in ("-c", "-t", "-tb", "-ngl")] == ["8192", "2", "2", "7"]
        await engine.start(replace(settings, temperature=0.2))
        assert len(launches) == 1
        await engine.start(replace(settings, context_size=4096))
        assert len(launches) == 2
    finally:
        await engine.stop()
