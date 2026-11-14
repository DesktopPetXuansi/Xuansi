"""热键注册及保存回滚导致 ID 环绕时，保留原来的有效绑定。"""

from types import SimpleNamespace

from pet.hotkey import GlobalHotkey


def test_rollback_wrap_skips_active_id_and_keeps_old_binding(monkeypatch):
    registered = {}

    def register(_, identifier, modifiers, code):
        assert identifier not in registered, "不能复用仍在使用的热键 ID"
        registered[identifier] = (modifiers, code)
        return True

    monkeypatch.setattr("pet.hotkey.USER32.RegisterHotKey", register)
    monkeypatch.setattr("pet.hotkey.USER32.UnregisterHotKey", lambda _, identifier: registered.pop(identifier))
    app = SimpleNamespace(installNativeEventFilter=lambda _: None, removeNativeEventFilter=lambda _: None)
    binding = GlobalHotkey(app, lambda: None)
    try:
        binding.stage("Ctrl+Alt+Space")
        binding.commit()
        active = binding.active
        assert isinstance(active, int)
        for _ in range(512):
            binding.stage("Ctrl+Alt+Q")
            binding.rollback()
            assert binding.active == active and set(registered) == {active}
        binding.stage("Ctrl+Alt+Q")
        binding.commit()
        assert binding.active != active and set(registered) == {binding.active}
    finally:
        binding.close()
    assert not registered
