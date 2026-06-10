from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import ROOT


# Tool packs are an Open-SCP-079 concept (SillyTavern cards stay pure persona).
# A pack is a named, composable bundle of tool names that you bind to ANY persona
# at launch — so "what it is" (card) and "what it can do" (pack) are independent.
TOOLPACKS_DIR = ROOT / "toolpacks"


@dataclass
class ToolPack:
    name: str = ""
    description: str = ""
    tools: list[str] = field(default_factory=list)
    note: str = ""  # optional extra system guidance appended when this pack is active
    source_path: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "ToolPack":
        p = Path(path)
        d = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            name=str(d.get("name", p.stem)),
            description=str(d.get("description", "")),
            tools=[str(t) for t in (d.get("tools", []) or [])],
            note=str(d.get("note", "")),
            source_path=str(p),
        )


def resolve_toolpack_path(value: str) -> Path | None:
    """A toolpack setting is either a bare name ('sandbox') or a .json path."""
    v = (value or "").strip()
    if not v:
        return None
    if v.endswith(".json") or "/" in v or "\\" in v:
        p = Path(v).expanduser()
    else:
        p = TOOLPACKS_DIR / f"{v}.json"
    return p if p.exists() else None


def load_toolpack(value: str) -> ToolPack | None:
    p = resolve_toolpack_path(value)
    if p is None:
        return None
    return ToolPack.load(p)
