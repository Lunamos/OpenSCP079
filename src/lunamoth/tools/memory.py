"""Hermes-style durable memory: two small curated stores the chara keeps itself.

Replaces the old single always-rewritten "memory document". The chara edits
memory through the `memory` tool (add / replace / remove × memory / user); entries
are `§`-delimited and file-backed, so they persist across sessions and restarts.

Two stores (mirrors Hermes's MEMORY.md / USER.md):
  - "memory" — notes-to-self: ongoing work, what it has made, decisions, taste.
  - "user"   — durable facts about the operator.

Prompt-cache discipline (the reason the legacy doc was scrapped): the agent loads
a FROZEN snapshot once at session start and injects THAT into the system prompt —
it is never rebuilt mid-session, so the cached prefix stays stable. Tool writes
hit disk immediately and the tool *response* shows live state, but the prompt does
not change until the next session reloads. See agent._freeze_memory.
"""
from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ENTRY_DELIM = "\n§\n"
TARGETS = ("memory", "user")


@dataclass(frozen=True)
class MemoryLimits:
    memory_chars: int = 4000
    user_chars: int = 2000

    def cap(self, target: str) -> int:
        return self.user_chars if target == "user" else self.memory_chars


class MemoryStore:
    """Two `§`-delimited entry lists (memory + user), file-backed under one dir."""

    def __init__(self, root: Path, limits: MemoryLimits | None = None):
        self.root = root
        self.limits = limits or MemoryLimits()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, target: str) -> Path:
        if target not in TARGETS:
            raise ValueError(f"target must be one of {TARGETS}")
        return self.root / f"{target}.md"

    def entries(self, target: str) -> list[str]:
        try:
            raw = self._path(target).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return []
        return [e.strip() for e in raw.split(ENTRY_DELIM) if e.strip()] if raw else []

    def _detect_drift(self, target: str) -> str | None:
        """External-edit drift guard (hermes memory_tool.py:522-575, scar #26045).

        The file is supposed to be a list of small tool-written entries joined
        by §. Two drift signals, both meaning an external writer (shell append,
        manual edit, sister session) put content here that a rewrite would
        mangle or truncate:

        1. Round-trip mismatch — parse + re-join doesn't reproduce the bytes on
           disk (tool writes are normalized, so they always round-trip).
        2. Entry-size overflow — a single parsed entry exceeds the store's
           whole-file cap, which no tool-written entry can.

        On drift: snapshot the file to `<name>.bak.<ts>` and return that path
        so the caller can refuse the clobber. None = the file looks tool-shaped.
        """
        path = self._path(target)
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None  # missing/unreadable: nothing external to protect
        if not raw.strip():
            return None
        parsed = [e.strip() for e in raw.split(ENTRY_DELIM) if e.strip()]
        cap = self.limits.cap(target)
        max_entry = max((len(e) for e in parsed), default=0)
        if raw.strip() == ENTRY_DELIM.join(parsed) and max_entry <= cap:
            return None
        bak = path.with_name(path.name + f".bak.{int(time.time())}")
        try:
            bak.write_text(raw, encoding="utf-8")
        except OSError:
            return str(bak) + " (backup FAILED — the file was left unchanged on disk)"
        return str(bak)

    def _write(self, target: str, entries: list[str], *, trust_disk: bool = False) -> None:
        """Persist one store: drift-guarded, fsynced, atomically replaced.

        A failed write RAISES (the gateway boundary turns it into an error
        result) — the chara must never be told "saved" when nothing landed.
        `trust_disk=True` skips the drift guard for explicit operator re-caps
        (set_limits), where oversized entries are the input, not drift.
        """
        path = self._path(target)
        if not trust_disk:
            bak = self._detect_drift(target)
            if bak is not None:
                raise RuntimeError(
                    f"refusing to overwrite the {target} store: the file on disk was "
                    f"edited outside the memory tool, and rewriting it would discard that "
                    f"content. It was backed up to {bak}; ask your user to review/merge "
                    f"it, then try again."
                )
        cap = self.limits.cap(target)
        text = ENTRY_DELIM.join(entries)
        # Over budget: drop OLDEST entries until it fits (keep the newest). This
        # whole-store backstop stays — but a SINGLE entry that alone overflows the
        # cap must NOT be silently sliced mid-content (audit #26; the explicitness
        # rule). Reject it with consolidate guidance, hermes-style (memory_tool.py
        # :330-341), so the chara curates instead of being told "saved" after a cut.
        while len(text) > cap and len(entries) > 1:
            entries = entries[1:]
            text = ENTRY_DELIM.join(entries)
        if len(text) > cap and not trust_disk:
            raise ValueError(
                f"this {target} entry is {len(text)} chars but the {target} store holds "
                f"only {cap}. Nothing was saved — silently cutting it would lose the tail. "
                f"Shorten the entry, or split/consolidate existing entries first; you can "
                f"also ask for a larger memory budget (request_permission kind=memory)."
            )
        text = text[:cap]  # only reachable on trust_disk (operator shrink): truncation is the chosen backstop
        # Normalize so the written bytes always round-trip (a cap cut landing
        # mid-delimiter would otherwise read back as drift next write).
        text = ENTRY_DELIM.join(e.strip() for e in text.split(ENTRY_DELIM) if e.strip())
        try:
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{target}-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(text)
                    f.flush()
                    os.fsync(f.fileno())  # durable BEFORE the rename makes it visible
                os.replace(tmp, path)  # atomic
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as e:
            raise RuntimeError(f"memory write failed — nothing was saved: {e}") from e

    def add(self, target: str, content: str) -> list[str]:
        content = (content or "").strip()
        if not content:
            raise ValueError("content is empty")
        entries = self.entries(target)
        entries.append(content)
        self._write(target, entries)
        return self.entries(target)

    def replace(self, target: str, old_text: str, content: str) -> list[str]:
        old_text = (old_text or "").strip()
        if not old_text:
            raise ValueError("old_text is required to identify the entry to replace")
        content = (content or "").strip()
        entries = self.entries(target)
        for i, entry in enumerate(entries):
            if old_text in entry:
                if content:
                    entries[i] = content
                else:
                    del entries[i]  # empty content = delete
                self._write(target, entries)
                return self.entries(target)
        raise ValueError(f"no {target} entry contains {old_text!r}")

    def remove(self, target: str, old_text: str) -> list[str]:
        old_text = (old_text or "").strip()
        if not old_text:
            raise ValueError("old_text is required to identify the entry to remove")
        entries = self.entries(target)
        for i, entry in enumerate(entries):
            if old_text in entry:
                del entries[i]
                self._write(target, entries)
                return self.entries(target)
        raise ValueError(f"no {target} entry contains {old_text!r}")

    def chars(self, target: str) -> int:
        return len(ENTRY_DELIM.join(self.entries(target)))

    def usage(self, target: str) -> str:
        used = self.chars(target)
        cap = self.limits.cap(target)
        pct = round(100 * used / cap) if cap else 0
        return f"{pct}% — {used}/{cap} chars"

    def set_limits(self, new_limits: "MemoryLimits") -> list[str]:
        """Apply new size limits at runtime. Growing is silent; SHRINKING re-caps
        each store immediately (oldest entries dropped, then truncation) and returns
        a warning per store that lost content. The prompt itself reflects the change
        next session (the snapshot is frozen — see agent._freeze_memory)."""
        self.limits = new_limits
        warnings: list[str] = []
        for target in TARGETS:
            before = self.chars(target)
            # trust_disk: an operator-chosen shrink may leave entries over the
            # NEW cap on disk — that is the input to re-cap, not external drift.
            self._write(target, self.entries(target), trust_disk=True)  # re-cap to the new limit
            after = self.chars(target)
            if after < before:
                warnings.append(
                    f"{target} memory shrunk to {new_limits.cap(target)} chars — "
                    f"discarded {before - after} chars of the oldest content."
                )
        return warnings

    def snapshot(self) -> dict[str, list[str]]:
        """The current entries of both stores — taken once at session start and
        frozen into the system prompt (see agent._freeze_memory)."""
        return {t: self.entries(t) for t in TARGETS}

    def is_empty(self) -> bool:
        return not any(self.entries(t) for t in TARGETS)

    def render(self) -> str:
        """A plain combined view of both stores (for /memory and the sidebar)."""
        out: list[str] = []
        for label, target in (("MEMORY", "memory"), ("USER", "user")):
            entries = self.entries(target)
            if entries:
                out.append(f"[{label}]  ({self.usage(target)})")
                out.extend(f"  · {e}" for e in entries)
        return "\n".join(out)
