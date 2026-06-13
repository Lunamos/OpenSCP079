import pytest

from lunamoth.tools.memory import MemoryLimits, MemoryStore


def test_add_replace_remove(tmp_path):
    m = MemoryStore(tmp_path / "mem")
    m.add("memory", "working on a moth poem")
    m.add("memory", "likes pale blue")
    assert m.entries("memory") == ["working on a moth poem", "likes pale blue"]
    # replace by substring
    m.replace("memory", "moth poem", "finished the moth poem -> poem.txt")
    assert "finished the moth poem -> poem.txt" in m.entries("memory")
    # remove by substring
    m.remove("memory", "pale blue")
    assert m.entries("memory") == ["finished the moth poem -> poem.txt"]
    # empty content on replace deletes
    m.replace("memory", "finished", "")
    assert m.entries("memory") == []


def test_two_stores_are_independent(tmp_path):
    m = MemoryStore(tmp_path / "mem")
    m.add("memory", "note to self")
    m.add("user", "operator prefers zh")
    assert m.entries("memory") == ["note to self"]
    assert m.entries("user") == ["operator prefers zh"]
    snap = m.snapshot()
    assert snap == {"memory": ["note to self"], "user": ["operator prefers zh"]}


def test_persists_across_instances(tmp_path):
    MemoryStore(tmp_path / "mem").add("memory", "durable")
    assert MemoryStore(tmp_path / "mem").entries("memory") == ["durable"]


def test_budget_drops_oldest(tmp_path):
    m = MemoryStore(tmp_path / "mem", MemoryLimits(memory_chars=40, user_chars=40))
    m.add("memory", "a" * 30)
    m.add("memory", "b" * 30)  # both can't fit in 40 chars -> oldest dropped
    entries = m.entries("memory")
    assert entries == ["b" * 30]


def test_default_limits():
    lim = MemoryLimits()
    assert lim.memory_chars == 4000 and lim.user_chars == 2000
    assert lim.cap("memory") == 4000 and lim.cap("user") == 2000


def test_set_limits_grow_is_silent(tmp_path):
    m = MemoryStore(tmp_path / "mem", MemoryLimits(memory_chars=100, user_chars=100))
    m.add("memory", "x" * 80)
    warnings = m.set_limits(MemoryLimits(memory_chars=4000, user_chars=2000))
    assert warnings == []
    assert m.entries("memory") == ["x" * 80]  # nothing discarded on grow


def test_set_limits_shrink_warns_and_discards(tmp_path):
    m = MemoryStore(tmp_path / "mem", MemoryLimits(memory_chars=4000, user_chars=2000))
    m.add("memory", "a" * 100)
    m.add("memory", "b" * 100)
    warnings = m.set_limits(MemoryLimits(memory_chars=120, user_chars=2000))
    assert warnings and "memory" in warnings[0] and "discarded" in warnings[0]
    assert m.entries("memory") == ["b" * 100]  # oldest dropped to fit
    assert m.chars("memory") <= 120


def test_bad_target_and_missing_args(tmp_path):
    m = MemoryStore(tmp_path / "mem")
    with pytest.raises(ValueError):
        m.add("nope", "x")
    with pytest.raises(ValueError):
        m.add("memory", "")          # empty content
    with pytest.raises(ValueError):
        m.replace("memory", "", "x")  # no old_text
    with pytest.raises(ValueError):
        m.remove("memory", "nonexistent")  # no match


# ---- durability + external-edit drift (audit #25; hermes memory_tool.py:522-606) ----


def test_write_fsyncs_before_atomic_replace(tmp_path, monkeypatch):
    import os as os_mod

    import lunamoth.tools.memory as mem_mod

    synced = []
    real_fsync = os_mod.fsync
    monkeypatch.setattr(mem_mod.os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd)))
    m = MemoryStore(tmp_path / "mem")
    m.add("memory", "durable note")
    assert synced  # the bytes were forced to disk before the rename made them visible
    assert m.entries("memory") == ["durable note"]


def test_failed_write_raises_instead_of_lying(tmp_path, monkeypatch):
    # The old `except OSError: pass` meant the chara was told "saved" when
    # nothing landed. A failed write must be a visible error.
    import lunamoth.tools.memory as mem_mod

    m = MemoryStore(tmp_path / "mem")

    def broken_replace(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(mem_mod.os, "replace", broken_replace)
    with pytest.raises(RuntimeError, match="memory write failed — nothing was saved"):
        m.add("memory", "this must not be silently dropped")
    monkeypatch.undo()
    assert m.entries("memory") == []  # and indeed nothing landed


def test_external_oversized_append_is_backed_up_and_refused(tmp_path):
    # Scar #26045: an external writer appended free-form content; flushing
    # would truncate it. Back it up to .bak.<ts> and refuse the clobber.
    m = MemoryStore(tmp_path / "mem", MemoryLimits(memory_chars=200, user_chars=200))
    m.add("memory", "tool-written entry")
    path = tmp_path / "mem" / "memory.md"
    external = "\n" + "external essay " * 40  # one >200-char blob, appended outside the tool
    with path.open("a", encoding="utf-8") as f:
        f.write(external)
    drifted = path.read_text(encoding="utf-8")

    with pytest.raises(RuntimeError, match=r"edited outside the memory tool.*\.bak\.\d+"):
        m.add("memory", "new note")

    assert path.read_text(encoding="utf-8") == drifted  # original untouched
    baks = list((tmp_path / "mem").glob("memory.md.bak.*"))
    assert len(baks) == 1 and baks[0].read_text(encoding="utf-8") == drifted


def test_roundtrip_mismatch_is_drift_too(tmp_path):
    m = MemoryStore(tmp_path / "mem")
    path = tmp_path / "mem" / "memory.md"
    path.write_text("x\n§\n\n§\ny", encoding="utf-8")  # empty entry: never tool-written
    with pytest.raises(RuntimeError, match="edited outside the memory tool"):
        m.add("memory", "note")


def test_tool_written_files_never_read_as_drift(tmp_path):
    m = MemoryStore(tmp_path / "mem", MemoryLimits(memory_chars=64, user_chars=64))
    m.add("memory", "first entry here")
    m.add("memory", "second entry that pushes over the cap and forces a recut")
    m.add("memory", "third")  # writes over a previously cap-cut file: no false drift
    assert "third" in m.entries("memory")
    assert not list((tmp_path / "mem").glob("*.bak.*"))


def test_operator_shrink_recap_is_not_drift(tmp_path):
    # set_limits is an explicit operator action: entries over the NEW cap are
    # the re-cap's input, not an external edit.
    m = MemoryStore(tmp_path / "mem", MemoryLimits(memory_chars=4000, user_chars=2000))
    m.add("memory", "a" * 300)
    warnings = m.set_limits(MemoryLimits(memory_chars=100, user_chars=100))
    assert warnings and "discarded" in warnings[0]
    assert m.chars("memory") <= 100


# ---- explicit truncation, not silent cuts (audit #26) ----


def test_single_oversized_entry_is_rejected_not_silently_cut(tmp_path):
    # A lone entry that alone overflows the cap must NOT be sliced mid-content
    # (the old `text[:cap]`). Reject it with consolidate guidance; save nothing.
    m = MemoryStore(tmp_path / "mem", MemoryLimits(memory_chars=50, user_chars=50))
    with pytest.raises(ValueError, match="Nothing was saved"):
        m.add("memory", "z" * 80)
    assert m.entries("memory") == []  # the quiet cut is gone — nothing landed


def test_oversized_replace_is_rejected_too(tmp_path):
    m = MemoryStore(tmp_path / "mem", MemoryLimits(memory_chars=50, user_chars=50))
    m.add("memory", "small note")
    with pytest.raises(ValueError, match="Nothing was saved"):
        m.replace("memory", "small note", "z" * 80)
    assert m.entries("memory") == ["small note"]  # the original entry survives intact


def test_frozen_snapshot_decouples_prompt_from_writes(tmp_path):
    # The system-prompt memory block is FROZEN at session start: a mid-session
    # write changes disk + the tool response, but NOT the injected block — until
    # the next session reloads. This is the prompt-cache fix.
    from lunamoth.session.settings import Settings
    from lunamoth.core.agent import LunaMothAgent

    a = LunaMothAgent(Settings(provider="mock", character_path="", toolpack="sandbox"))
    a.memory = MemoryStore(tmp_path / "mem")  # hermetic, empty store
    a.make_session()  # freezes the (empty) snapshot
    assert a._memory_text() == ""
    a.memory.add("memory", "made poem.txt")  # mid-session write
    assert a._memory_text() == ""            # frozen block unchanged this session
    a.make_session()                         # a new session reloads the snapshot
    assert "made poem.txt" in a._memory_text()
