"""Diagnostic logging, hermes_logging.py-style (stdlib, MIT-credited design).

- Files live next to the audit trail: `<sandbox>/logs/lunamoth.log` (everything)
  and `errors.log` (WARNING+). One chara = one process = one log dir.
- Every record carries the chara name (LUNAMOTH_SESSION) so logs copied off a
  box stay attributable.
- A redacting filter scrubs API keys / bearer tokens before anything reaches
  disk (hermes's _RedactingFormatter rule).
- NOTHING goes to stdout/stderr — the TUI owns the terminal. `LUNAMOTH_DEBUG=1`
  or `--debug` raises the level to DEBUG (Claude Code's --debug analog).
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import re
from pathlib import Path

from ..config import SANDBOX_ROOT
from .broker import broker

_FORMAT = "%(asctime)s %(levelname)-7s [%(session)s] %(name)s: %(message)s"
_REDACT = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+\S+|api[_-]?key[\"':=\s]+\S+)", re.I)

_configured = False


def debug_enabled() -> bool:
    return os.getenv("LUNAMOTH_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


class _SessionAndRedact(logging.Filter):
    """Inject the chara name + scrub credentials, in one pass per record."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        scrubbed = _REDACT.sub("•••", message)
        if scrubbed != message:
            record.msg, record.args = scrubbed, ()
        record.session = os.getenv("LUNAMOTH_SESSION", "-")
        return True


def log_dir() -> Path:
    return SANDBOX_ROOT / "logs"


def setup_logging(debug: "bool | None" = None, directory: "Path | None" = None, force: bool = False) -> Path:
    """Idempotent setup; returns the log directory. `force` rebuilds handlers
    (tests, or pointing at a different directory)."""
    global _configured
    root = logging.getLogger("lunamoth")
    if _configured and not force:
        return log_dir()
    for h in list(root.handlers):
        root.removeHandler(h)
        if h is not broker:  # the ring is a reusable singleton — keep it open
            h.close()
    if debug is None:
        debug = debug_enabled()
    target = Path(directory) if directory else log_dir()
    target.mkdir(parents=True, exist_ok=True)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.propagate = False  # never reach stderr — the TUI owns the terminal

    main = logging.handlers.RotatingFileHandler(
        target / "lunamoth.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    errors = logging.handlers.RotatingFileHandler(
        target / "errors.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    errors.setLevel(logging.WARNING)
    scrub = _SessionAndRedact()
    formatter = logging.Formatter(_FORMAT)
    broker.setFormatter(formatter)
    for handler in (main, errors, broker):
        handler.addFilter(scrub)
        if handler is not broker:
            handler.setFormatter(formatter)
        root.addHandler(handler)
    _configured = True
    return target


def get_logger(name: str) -> logging.Logger:
    """Component logger: get_logger('llm') -> 'lunamoth.llm'. Usable before
    setup_logging (records just go nowhere — propagate is only cut at setup)."""
    return logging.getLogger(f"lunamoth.{name}")
