from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Neutral runtime environment state — character-agnostic. No trust/hostility or
# "containment" framing here: roleplay flavor belongs in the character card and
# world book, never in the engine. (SCP-079 gets its tone from its own card.)
DEFAULT_STATUS = {
    "isolation": "sandbox",          # dir | sandbox | docker (informational)
    "network_access": False,         # toggled live by the operator (/net on)
    "writable_paths": [],            # extra dirs the terminal tool may write to
    "tool_access": [
        "inspect_env", "read_memory", "write_memory", "list_files", "read_file",
        "list_workspace", "read_workspace_file", "write_file", "write_log", "terminal",
    ],
}

# Legacy SCP-flavored keys to drop from any persisted state written by old builds.
_LEGACY_KEYS = ("containment_level", "trust", "hostility", "memory_integrity")


class EnvState:
    """Persisted, mutable, neutral environment state for a session."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save(DEFAULT_STATUS)

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return dict(DEFAULT_STATUS)
        # Migrate state files written before the de-SCP / terminal-tool changes.
        changed = False
        for key in _LEGACY_KEYS:
            if key in data:
                data.pop(key, None)
                changed = True
        access = data.get("tool_access")
        if isinstance(access, list) and "run_python" in access:
            data["tool_access"] = [t for t in access if t != "run_python"]
            if "terminal" not in data["tool_access"]:
                data["tool_access"].append("terminal")
            changed = True
        if isinstance(access, list) and "inspect_cell" in data.get("tool_access", []):
            data["tool_access"] = ["inspect_env" if t == "inspect_cell" else t for t in data["tool_access"]]
            changed = True
        data.setdefault("isolation", "sandbox")
        if changed:
            self.save(data)
        return data

    def save(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_network(self, allowed: bool) -> dict[str, Any]:
        data = self.load()
        data["network_access"] = bool(allowed)
        self.save(data)
        return data

    def add_writable_path(self, path: str) -> dict[str, Any]:
        data = self.load()
        paths = list(data.get("writable_paths", []))
        if path not in paths:
            paths.append(path)
        data["writable_paths"] = paths
        self.save(data)
        return data


# Backward-compatible alias for older imports.
ContainmentState = EnvState
