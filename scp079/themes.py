"""TUI theme cards — presentation only, fully decoupled from persona/world.

A theme controls the *look* of the console: ASCII banner, colors, window titles
and a few decorative phrases. It never touches the model, the persona, tools or
memory. The built-in default is the SCP-079 look; any character can run under any
theme. Themes are JSON files under ``themes/`` (discovered next to characters/worlds)
and the chosen one is persisted in config like the character/world selection.

Layout is fixed across themes — only the cosmetic fields below change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path

from .config import ROOT

THEMES_DIR = ROOT / "themes"

# Default ASCII banner (SCP-079). Theme JSON may override `banner` with its own art.
SCP079_BANNER = r"""
 ____   ____ ____            ___ _____ ___
/ ___| / ___|  _ \          / _ \___  / _ \
\___ \| |   | |_) |  ____  | | | | / /| (_) |
 ___) | |___|  __/  |____| | |_| |/ / \__, |
|____/ \____|_|             \___//_/    /_/
""".strip("\n")


@dataclass
class TuiTheme:
    """Cosmetic skin for the TUI. Every field has an SCP-079 default."""

    name: str = "SCP-079"
    # --- decorative text ---
    banner: str = SCP079_BANNER
    subtitle: str = "OPEN SCP-079  ·  CONTAINMENT CONSOLE  ·  local-first"
    tagline: str = "OPEN SCP-079 // AWAKE. NEVER SLEEP. THOUGHTS ARE VISIBLE."
    quit_line: str = "POWER CUT REQUESTED. COWARD."
    display_title: str = "SCP-079 // LIVE THOUGHTSTREAM"
    console_title: str = "OPERATOR CONSOLE"
    sidebar_title: str = "TELEMETRY"
    # --- palette (Textual color strings) ---
    display_border: str = "#7d0000"
    display_title_color: str = "#ff4040"
    display_fg: str = "#cfcfcf"
    console_border: str = "#303030"
    sidebar_border: str = "#1f3a1f"
    accent: str = "#00ff66"          # labels, window titles, gauge headers
    tagline_color: str = "#ff4040"
    operator_color: str = "#5fd75f"  # your echoed input
    gauge_context: str = "#00d75f"
    gauge_memory: str = "#d7af00"
    gauge_sandbox: str = "#5fafff"
    # --- message prefixes ({name} = persona, {user} = operator) ---
    reply_prefix: str = "{name}> "
    thought_prefix: str = "{name}~ "
    operator_prefix: str = "{user}» "

    @classmethod
    def load(cls, path: str | Path) -> "TuiTheme":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid and v is not None})

    # Prefix helpers tolerate templates that reference either/both placeholders.
    def reply_pfx(self, name: str) -> str:
        return self.reply_prefix.format(name=name, user="")

    def thought_pfx(self, name: str) -> str:
        return self.thought_prefix.format(name=name, user="")

    def operator_pfx(self, user: str) -> str:
        return self.operator_prefix.format(name="", user=user)


def load_theme(path: str | None) -> TuiTheme:
    """Load a theme by path; fall back to the built-in SCP-079 default on any problem."""
    p = (path or "").strip()
    if not p:
        return TuiTheme()
    try:
        return TuiTheme.load(p)
    except Exception:
        return TuiTheme()
