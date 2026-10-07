import pytest

from pet.memory import MemoryStore


def test_explicit_memory_survives_restart(tmp_path):
    memory = MemoryStore(tmp_path / "memory.json")
    assert memory.remember("我喜欢简短的回答")
    assert MemoryStore(memory.path).read() == "我喜欢简短的回答"
    # 意图由推理层验证；这里仅检查模型确认事项的持久化和去重。
    memory.remember("我喜欢简短的回答")
    assert len(memory.read().splitlines()) == 1


def test_secret_is_rejected_and_clear_erases_saved_notes(tmp_path):
    memory = MemoryStore(tmp_path / "memory.json")
    with pytest.raises(ValueError):
        memory.remember("我的密码是123456")
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


def test_manual_edit_can_save_more_than_the_dialogue_item_limit(tmp_path):
    """500 字仅约束对话新增事项；手动编辑失败时也不能覆盖已保存内容。"""
    memory = MemoryStore(tmp_path / "memory.json")
    note = "例" * 501
    memory.save(note)

    assert memory.read() == note
    with pytest.raises(ValueError, match="1–500"):
        memory.remember("另" * 501)
    assert memory.read() == note


def test_manual_edit_keeps_the_total_limit_and_previous_content(tmp_path):
    """手动编辑允许长段落，但不能突破总量或在拒绝后丢失旧记忆。"""
    memory = MemoryStore(tmp_path / "memory.json")
    note = "例" * 6000
    memory.save(note)

    with pytest.raises(ValueError, match="6000"):
        memory.save(note + "例")
    assert memory.read() == note
