"""Interaction modes and card-driven enter/leave prompt resolution.

The mode answers ONE question: how does the chara behave while the operator is
attached? (Detached background life is not a mode — `lunamoth start/stop` is
the on/off switch for that, and the daemon always self-runs.)

    live   it keeps living — greets you on attach, then carries on with its own
           thinking/creating loop while you watch; you can interject anytime.
           After the greeting there is a grace pause so you get the first word
           if you want it; if you stay silent it simply returns to its work.
    chat   it attends to you — greets you on attach, then waits; it only ever
           speaks in reply. No self-talk while you're attached.

Both modes carry full presence awareness: attach/detach prompts (if the card
declares them) and the user_present flag that gates permission requests.
"""
from __future__ import annotations

from ..worldinfo import apply_macros

MODES = ("live", "chat")
DEFAULT_MODE = "live"

# Pre-rename spellings (presence auto|always|off, forever on|off) seen in old
# config files / muscle memory — map them onto the two modes.
_LEGACY = {"auto": "live", "always": "live", "on": "live", "off": "chat"}


def normalize_mode(value: str) -> str:
    v = (value or "").strip().lower()
    if v in MODES:
        return v
    return _LEGACY.get(v, DEFAULT_MODE)


def _card_prompt(card, key: str) -> str:
    """A presence prompt declared by the card (extensions.lunamoth.<key>), if any."""
    if card is None:
        return ""
    for source in (card.defaults(), card.extensions):
        v = source.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def attach_text(card, char: str, user: str) -> str:
    """The card's arrival prompt, macros applied. Empty when the card declares none."""
    raw = _card_prompt(card, "on_attach")
    return apply_macros(raw, char, user) if raw else ""


def detach_text(card, char: str, user: str) -> str:
    """The card's departure prompt, macros applied. Empty when the card declares none."""
    raw = _card_prompt(card, "on_detach")
    return apply_macros(raw, char, user) if raw else ""
