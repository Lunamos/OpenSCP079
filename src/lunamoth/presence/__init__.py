"""Presence awareness — the character knows when the operator comes and goes.

A persistent chara runs forever in the background, but it should *feel* the
operator attach and detach. Presence is delivered as a NEUTRAL FACT, never a
forced reaction: entering the room is silent; the chara registers the operator
only when they actually SPEAK (an "entered" fact is injected before that first
message), and a "left" fact is injected on detach only if the operator spoke.

The wording of that fact is card-customizable (SillyTavern macros apply):

    extensions.lunamoth.on_attach   overrides the "<user> entered" marker text
    extensions.lunamoth.on_detach   overrides the "<user> left" marker text

With no override the engine uses a bundled NEUTRAL default in the card's
language. These are an Advanced card-editor field — card generation never
produces them. (They REPLACE the old on_attach/on_detach "reaction turn" hook:
the marker is a passive context line the chara reads on its next turn, not a
turn of its own — see prompts.marker_text.)

How the chara behaves WHILE the operator is attached is one per-chara setting
(Settings.mode, `/mode` to flip) with exactly two values — see prompts.py:

    live   (default) greets you, then keeps living its own loop while you watch
           (with a grace pause after the greeting so you can take the first word).
    chat   greets you, then attends to you only — no self-talk while attached.

Detached life is NOT a mode: `lunamoth start/stop` is that switch, and a
running daemon always self-runs. Being present is a FACT (user_present), not a
setting.

Cross-process handoff: when a TUI detaches, the detach event is queued in a
small state file inside the session sandbox; the background daemon consumes it
on startup so the chara's loop continues *knowing* the operator left. The same
file remembers whether the chara has ever met the operator (first boot shows
the card's first_mes once; later attaches open silently — the chara registers
the operator only when they speak).

Presence also gates the `request_permission` tool: while the operator is
attached the character may ask for network / writable paths / more resources
and wait for an answer (timeout = deny); while the operator is away every
request is auto-denied and merely logged.
"""
from .prompts import marker_text, normalize_mode
from .state import PresenceState

__all__ = [
    "PresenceState",
    "marker_text",
    "normalize_mode",
]
