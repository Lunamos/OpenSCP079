from __future__ import annotations

import shutil
from pathlib import Path

from .config import SANDBOX_ROOT


def clean_runtime_sandbox(clear_memory: bool = True) -> None:
    """Clean volatile containment artifacts.

    This is intentionally conservative: it removes logs, FIFO/control files,
    transient workspace files, and optionally zeros memory.txt. Static files in
    sandbox/files and containment_status.json are preserved.
    """
    logs = SANDBOX_ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    for p in logs.iterdir():
        if p.name == ".gitkeep":
            continue
        if p.is_file() or p.is_symlink():
            p.unlink(missing_ok=True)
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    (logs / ".gitkeep").touch()

    control = SANDBOX_ROOT / "control"
    control.mkdir(parents=True, exist_ok=True)
    for p in control.iterdir():
        if p.name == ".gitkeep":
            continue
        if p.is_file() or p.is_symlink() or p.is_fifo():
            p.unlink(missing_ok=True)
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    (control / ".gitkeep").touch()

    workspace = SANDBOX_ROOT / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    for p in workspace.iterdir():
        if p.name in {".gitkeep", "memory.txt"}:
            continue
        if p.is_file() or p.is_symlink():
            p.unlink(missing_ok=True)
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    (workspace / ".gitkeep").touch()
    if clear_memory:
        (workspace / "memory.txt").write_text("", encoding="utf-8")
    else:
        (workspace / "memory.txt").touch()
