"""The launcher / roster — what `lunamoth` opens to.

Hermes-style: it stays in the normal terminal (scrollback preserved), it does NOT
take over the screen. Only when you actually attach to a chara does the
full-screen TUI take over. So the flow is: a blue LunaMoth splash + a printed
roster of your charas, you pick one (or create one), and only then does the
alt-screen TUI open.

`run_launcher()` returns one of:
    ("attach", name) | ("new", None) | ("start_all", None) | ("stop", name) | None
The CLI acts on the result; this module never launches a chara itself.
"""
from __future__ import annotations

import datetime as _dt
import time

from rich.console import Console
from rich.text import Text

from . import art
from . import sessions as S

_STATUS = {
    "attached": ("◆", "#eafaff"),   # a live TUI is open
    "running": ("●", "#7fe0c0"),    # background daemon, thinking/creating
    "idle": ("○", "#6f8a99"),       # configured, not running
    "new": ("·", "#c8a86a"),        # never set up
}


def _ago(ts: float) -> str:
    if not ts:
        return "—"
    s = int((_dt.datetime.now() - _dt.datetime.fromtimestamp(ts)).total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def _splash(console: Console, animate: bool) -> None:
    compact = console.width < art.wordmark_width() + 2
    if animate and console.is_terminal:
        try:
            from rich.live import Live  # inline (screen=False) → stays in scrollback

            with Live(console=console, refresh_per_second=24, transient=False) as live:
                for frame in art.sweep_frames(compact):
                    live.update(Text.from_markup(frame))
                    time.sleep(0.04)
        except Exception:
            console.print(Text.from_markup(art.wordmark(compact)))
    else:
        console.print(Text.from_markup(art.wordmark(compact)))
    console.print(Text.from_markup(art.tagline()), justify="center" if compact else "left")
    console.print()


def _print_roster(console: Console, rows: list[S.SessionMeta]) -> None:
    if not rows:
        console.print("  [#6f8a99]no chara yet — press  n  to summon one[/]\n")
        return
    for i, meta in enumerate(rows, 1):
        status = meta.status()
        glyph, color = _STATUS.get(status, ("·", "#888888"))
        line = Text()
        line.append(f"  {i:>2}  ", style="#5f7d8c")
        line.append(f"{glyph} ", style=color)
        line.append(f"{meta.name:<16}", style="bold #dfeefa")
        line.append(f"{meta.character_label():<22}", style="#9fd9ff")
        line.append(f"{status:<9}", style=color)
        line.append(f"{meta.isolation:<8}", style="#5f7d8c")
        line.append(_ago(meta.last_active or meta.created_at), style="#5f7d8c")
        console.print(line)
    console.print()


def _hint(console: Console) -> None:
    h = Text("  ")
    for key, label in [("#", "attach"), ("n", "new"), ("s", "start all"), ("x N", "stop"), ("q", "quit")]:
        h.append(key + " ", style="#9fd9ff")
        h.append(label + "   ", style="#5f7d8c")
    console.print(h)


def run_launcher(animate: bool = True):
    """Render the roster in the terminal and read one choice. Returns an action tuple."""
    console = Console()
    console.print()
    _splash(console, animate)
    while True:
        rows = S.list_sessions()
        _print_roster(console, rows)
        _hint(console)
        try:
            raw = console.input("  [#9fd9ff]▸[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return None

        low = raw.lower()
        if low in ("", "q", "quit", "exit"):
            return None
        if low in ("n", "new"):
            return ("new", None)
        if low in ("s", "start", "start-all", "start all"):
            return ("start_all", None)
        if low in ("r", "refresh"):
            console.print()
            continue
        parts = low.split()
        if parts and parts[0] in ("x", "stop") and len(parts) == 2 and parts[1].isdigit():
            idx = int(parts[1]) - 1
            if 0 <= idx < len(rows):
                return ("stop", rows[idx].name)
        if low.isdigit():
            idx = int(low) - 1
            if 0 <= idx < len(rows):
                return ("attach", rows[idx].name)
        console.print("  [#c8704a]?[/] [#6f8a99]type a number to attach, or n / s / x N / q[/]\n")
