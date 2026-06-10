from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def apply_macros(text: str, char: str, user: str) -> str:
    if not text:
        return text
    # SillyTavern's core macros. We deliberately keep this small.
    return (
        text.replace("{{char}}", char)
        .replace("{{user}}", user)
        .replace("<USER>", user)
        .replace("<BOT>", char)
    )


@dataclass
class WorldEntry:
    keys: list[str] = field(default_factory=list)
    secondary_keys: list[str] = field(default_factory=list)
    content: str = ""
    constant: bool = False
    selective: bool = False
    enabled: bool = True
    order: int = 100
    comment: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorldEntry":
        # Accept both standalone-world fields and embedded character_book fields.
        keys = d.get("keys") or d.get("key") or []
        secondary = d.get("secondary_keys") or d.get("keysecondary") or []
        if isinstance(keys, str):
            keys = [keys]
        if isinstance(secondary, str):
            secondary = [secondary]
        enabled = d.get("enabled")
        if enabled is None:
            enabled = not bool(d.get("disable", False))
        order = d.get("insertion_order")
        if order is None:
            order = d.get("order", 100)
        return cls(
            keys=[str(k) for k in keys],
            secondary_keys=[str(k) for k in secondary],
            content=str(d.get("content", "")),
            constant=bool(d.get("constant", False)),
            selective=bool(d.get("selective", False)),
            enabled=bool(enabled),
            order=int(order) if str(order).lstrip("-").isdigit() else 100,
            comment=str(d.get("comment", "")),
        )

    def matches(self, scan_text: str) -> bool:
        """Constant entries always fire; otherwise any primary key must appear.

        When `selective` with secondary keys, at least one secondary key must
        also appear (a small subset of ST's AND/NOT logic — enough to be useful).
        """
        if not self.enabled:
            return False
        if self.constant:
            return True
        if not self.keys:
            return False
        haystack = scan_text.lower()
        primary_hit = any(k.lower() in haystack for k in self.keys if k)
        if not primary_hit:
            return False
        if self.selective and self.secondary_keys:
            return any(k.lower() in haystack for k in self.secondary_keys if k)
        return True


@dataclass
class Lorebook:
    name: str = ""
    entries: list[WorldEntry] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any], name: str = "") -> "Lorebook":
        raw = d.get("entries", d if "entries" not in d else {})
        items: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            items = list(raw.values())
        elif isinstance(raw, list):
            items = list(raw)
        entries = [WorldEntry.from_dict(e) for e in items if isinstance(e, dict)]
        return cls(name=d.get("name", name), entries=entries)

    @classmethod
    def load(cls, path: str | Path) -> "Lorebook":
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(data, name=p.stem)

    def activate(self, scan_text: str, char: str, user: str) -> list[str]:
        hits = [e for e in self.entries if e.matches(scan_text)]
        hits.sort(key=lambda e: e.order)
        return [apply_macros(e.content, char, user).strip() for e in hits if e.content.strip()]

    def render(self, scan_text: str, char: str, user: str) -> str:
        blocks = self.activate(scan_text, char, user)
        if not blocks:
            return ""
        return "[World Info / 世界书]\n" + "\n\n".join(blocks)
