"""Unit tests for companion.memory, isolated to a temp XDG_CONFIG_HOME.

memory._runtime_dir() reads XDG_CONFIG_HOME on each call, so pointing it at a
tmp dir keeps these tests off the real ~/.config.
"""

import pytest

from companion import memory


@pytest.fixture(autouse=True)
def _isolated_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def test_recent_rolls_at_cap_newest_first_then_trims():
    for i in range(memory.MAX_RECENT + 5):
        memory.append_recent(f"q{i}", f"a{i}")
    entries = memory.read_recent_entries()
    assert len(entries) == memory.MAX_RECENT          # rolled to the cap
    assert f"q{memory.MAX_RECENT + 4}" in entries[0]   # newest first
    memory.trim_recent(5)
    assert len(memory.read_recent_entries()) == 5


def test_append_fact_dedupes():
    memory.append_fact("likes tea")
    memory.append_fact("likes tea")     # duplicate ignored
    memory.append_fact("uses windows")
    assert memory.facts_list() == ["likes tea", "uses windows"]


def test_write_facts_replaces_and_strips():
    memory.append_fact("old")
    memory.write_facts(["new1", "  new2  ", "  "])
    assert memory.facts_list() == ["new1", "new2"]


def test_read_missing_file_returns_empty():
    assert memory.read_recent_entries() == []
    assert memory.facts_list() == []


def test_write_task_keeps_rolling_progress_and_mirrors_current(tmp_path):
    for i in range(memory.MAX_TASK_PROGRESS + 3):
        memory.write_task("sess1", "build the thing", f"step {i}")
    task = (tmp_path / "opencode" / "agent" / "slime" / "tasks" / "sess1.md").read_text(encoding="utf-8")
    assert "build the thing" in task
    assert task.count("- [") == memory.MAX_TASK_PROGRESS    # only last-N progress kept
    current = (tmp_path / "opencode" / "agent" / "slime" / "task_current.md").read_text(encoding="utf-8")
    assert current == task                                   # task_current mirrors active task
