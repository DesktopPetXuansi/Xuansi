import pytest

from pet.memory import MemoryStore


def test_explicit_memory_survives_restart(tmp_path):
    memory = MemoryStore(tmp_path / "memory.json")
    assert memory.remember_explicit("记住，我喜欢简短的回答")
    assert MemoryStore(memory.path).read() == "我喜欢简短的回答"
    assert not memory.remember_explicit("这个屏幕上是什么")
    memory.remember_explicit("记住，我喜欢简短的回答")
    assert len(memory.read().splitlines()) == 1


def test_secret_is_rejected_and_clear_erases_saved_notes(tmp_path):
    memory = MemoryStore(tmp_path / "memory.json")
    with pytest.raises(ValueError):
        memory.remember_explicit("记住我的密码是123456")
    assert not memory.path.exists()
    memory.save("我喜欢猫")
    memory.save("")
    assert MemoryStore(memory.path).read() == ""


def test_context_prioritizes_relevant_memory_within_budget(tmp_path):
    memory = MemoryStore(tmp_path / "memory.json")
    memory.save("我喜欢喝绿茶\n" + "\n".join(f"普通备注第{i}条" for i in range(120)))
    context = memory.context("我喜欢喝什么？", limit=100)
    assert context.startswith("我喜欢喝绿茶")
    assert len(context) <= 100
