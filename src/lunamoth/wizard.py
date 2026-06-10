"""Plain-terminal setup wizard, in the style of `hermes setup`.

Runs before the TUI: sequential numbered prompts on stdin/stdout, so it works
over SSH, in dumb terminals, and is trivially debuggable. The in-TUI settings
screen (Ctrl+S) remains for hot-swapping once a session is running.

Must be imported only after the CLI has exported the session env vars, because
`settings` resolves its config path at import time.
"""
from __future__ import annotations

import getpass
import sys

from .settings import PRESETS, Settings, load_settings, save_settings


def _say(text: str = "") -> None:
    print(text, flush=True)


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        raw = input(f"  {prompt}{suffix}: ").strip()
    except EOFError:
        raw = ""
    return raw or default


def _choose(prompt: str, options: list[str], default_index: int = 0) -> int:
    _say(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        marker = "*" if (i - 1) == default_index else " "
        _say(f"   {marker} {i}) {opt}")
    while True:
        raw = _ask("choice", str(default_index + 1))
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        _say(f"  please enter 1-{len(options)}")


def _test(settings: Settings) -> bool:
    from .llm import LLMClient

    if not settings.is_live():
        _say("  (offline/mock provider — nothing to test)")
        return True
    _say("  testing connection ...")
    ok, msg = LLMClient(settings.to_llm_config()).test_connection()
    _say(f"  {'✓' if ok else '✗'} {msg}")
    return ok


def run_wizard(non_interactive_ok: bool = True) -> Settings:
    """Collect provider/model/persona settings interactively and persist them."""
    settings = load_settings()

    if not sys.stdin.isatty():
        if non_interactive_ok:
            _say("non-interactive terminal: keeping existing/env settings.")
            _say("configure manually via env vars or edit the session config.json.")
            save_settings(settings)
            return settings
        raise RuntimeError("setup wizard needs an interactive terminal")

    _say("LunaMoth setup — press Enter to accept the [default] of any question.")

    preset_names = list(PRESETS.keys()) + ["Custom OpenAI-compatible endpoint"]
    idx = _choose("Model provider:", preset_names, 0)
    if idx < len(PRESETS):
        preset = PRESETS[preset_names[idx]]
        settings.provider = preset.get("provider", settings.provider)
        settings.base_url = preset.get("base_url", "")
        settings.api_key = preset.get("api_key", settings.api_key)
        settings.model = preset.get("model", settings.model)
    else:
        settings.provider = "openai_compatible"

    if settings.provider != "mock":
        settings.base_url = _ask("base_url", settings.base_url)
        try:
            key = getpass.getpass(f"  api_key [{'set' if settings.api_key else 'empty'}]: ").strip()
        except EOFError:
            key = ""
        if key:
            settings.api_key = key
        settings.model = _ask("model", settings.model)
        if not _test(settings) and _choose("Connection failed. Continue anyway?", ["re-enter model/key", "continue"], 0) == 0:
            return run_wizard()

    settings.user_name = _ask("Your name ({{user}})", settings.user_name)

    _say("\nCharacter: default is LunaMoth 月蛾 (language follows the card; pick others with Ctrl+S in the TUI).")

    path = save_settings(settings)
    _say(f"\nsaved → {path}")
    return settings
