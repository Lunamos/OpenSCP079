from __future__ import annotations

import locale
import os
from pathlib import Path

from .config import ROOT

# Name shown only when no character card can be loaded at all.
DEFAULT_NAME = "LunaMoth"

# Last-resort fallback persona, used only if the bundled default card is missing.
# Deliberately character-neutral: the engine carries no roleplay flavor of its own.
_FALLBACK_PERSONA = {
    "zh": (
        "你是一个运行在本地沙盒里的 AI agent。简洁地表达，保持你自己的设定。\n"
        "（这是兜底人格，仅在默认角色卡缺失时使用；正常情况下请在启动时选择一张角色卡。）"
    ),
    "en": (
        "You are an AI agent running in a local sandbox. Be concise and stay in character.\n"
        "(Last-resort fallback persona, used only if the default card is missing; normally you pick a card at launch.)"
    ),
}


def system_language() -> str:
    """Best guess at the operator's language, used only to choose which bundled
    default card to pre-select. Once a card is chosen, language comes from the card."""
    env = os.getenv("LUNAMOTH_LANG", os.getenv("LUNAMOSS_LANG", "")).strip().lower()
    if env:
        return "zh" if env.startswith("zh") else "en"
    try:
        loc = (locale.getlocale()[0] or locale.getdefaultlocale()[0] or "").lower()
    except Exception:
        loc = ""
    return "zh" if loc.startswith(("zh", "chinese")) else "en"


def default_character_path(lang: str | None = None) -> Path | None:
    """Bundled default character (LunaMoth 月蛾) in the operator's language, if present."""
    lang = lang or system_language()
    p = ROOT / "characters" / f"LunaMoth.{lang}.json"
    return p if p.exists() else None


def default_world_path(lang: str | None = None) -> Path | None:
    """World book that pairs with the default character, if present."""
    lang = lang or system_language()
    p = ROOT / "worlds" / f"LunaMoth.{lang}.json"
    return p if p.exists() else None


def fallback_persona(lang: str = "en") -> str:
    return _FALLBACK_PERSONA["zh" if str(lang).startswith("zh") else "en"]
