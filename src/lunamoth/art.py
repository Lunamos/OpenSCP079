"""LunaMoth brand art: the serif wordmark, a pale-blue→white gradient, and a
small "moonlight" sweep animation. Shown on every launch (the roster/splash).

Cosmetic only. Kept restrained — this is a general runtime — but with a serif
wordmark + a moth motif so it reads as a roleplay tavern, not a dev tool.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets"

# Pale moonlit blue at the top fading to white at the bottom.
_TOP = (0x6D, 0xB3, 0xE0)
_BOTTOM = (0xFF, 0xFF, 0xFF)
_SWEEP = "#eafaff"   # the bright moonlight bar that crosses the wordmark
_DIM = "#5f7d8c"


@lru_cache(maxsize=4)
def _load(name: str) -> list[str]:
    try:
        raw = (_ASSETS / name).read_text(encoding="utf-8").rstrip("\n")
        return raw.split("\n")
    except OSError:
        return ["LunaMoth"]


def _blend(t: float) -> str:
    r = round(_TOP[0] + (_BOTTOM[0] - _TOP[0]) * t)
    g = round(_TOP[1] + (_BOTTOM[1] - _TOP[1]) * t)
    b = round(_TOP[2] + (_BOTTOM[2] - _TOP[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _row_color(i: int, n: int) -> str:
    return _blend(i / max(1, n - 1))


def _esc(s: str) -> str:
    # Rich markup: only [ is special; escape it so wordmark brackets render literally.
    return s.replace("[", "\\[")


def wordmark(compact: bool = False, sweep_x: int | None = None, sweep_w: int = 6) -> str:
    """Return the wordmark as Rich markup.

    sweep_x: center column of the moonlight highlight bar (None = static gradient).
    """
    rows = _load("wordmark_compact.txt" if compact else "wordmark.txt")
    n = len(rows)
    out: list[str] = []
    for i, row in enumerate(rows):
        base = _row_color(i, n)
        if sweep_x is None:
            out.append(f"[{base}]{_esc(row)}[/]")
            continue
        lo, hi = sweep_x - sweep_w, sweep_x + sweep_w
        a, b, c = row[:max(0, lo)], row[max(0, lo):max(0, hi)], row[max(0, hi):]
        seg = ""
        if a:
            seg += f"[{base}]{_esc(a)}[/]"
        if b:
            seg += f"[bold {_SWEEP}]{_esc(b)}[/]"
        if c:
            seg += f"[{base}]{_esc(c)}[/]"
        out.append(seg)
    return "\n".join(out)


def wordmark_width(compact: bool = False) -> int:
    return max((len(r) for r in _load("wordmark_compact.txt" if compact else "wordmark.txt")), default=0)


def sweep_frames(compact: bool = False, step: int = 4, sweep_w: int = 6) -> list[str]:
    """Frames for a one-shot moonlight sweep across the wordmark, then settle."""
    width = wordmark_width(compact)
    frames = [wordmark(compact, sweep_x=x, sweep_w=sweep_w) for x in range(-sweep_w, width + sweep_w, step)]
    frames.append(wordmark(compact, sweep_x=None))  # settle to static gradient
    return frames


def tagline(text: str = "an agentic character tavern · 月蛾") -> str:
    return f"[italic {_DIM}]{text}[/]"
