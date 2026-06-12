"""Run shell commands for the agent's `terminal` tool — Hermes/Claude-Code style.

The agent is given ONE language-agnostic capability: run a shell command in its
session workspace. Isolation is provided by the OS, not by intercepting a
specific interpreter, so there is no Python-only guard and no language lock-in.

Three isolation mechanisms (chosen per session, see `sessions.py`):

    dir      no jail — the command runs with your user's full privileges, cwd in
             the workspace (Claude-Code-style "I trust this directory"). Network
             always available.
    sandbox  OS jail: sandbox-exec (macOS) / bubblewrap (Linux). Writes confined
             to the workspace (+ any allow-listed paths); network gated by the
             runtime `allow_network` permission. The default.
    docker   container: read-only rootfs, bind-mounted workspace, network gated.

Permissions (allow_network, writable_paths) are read fresh on every call, so the
operator can flip them mid-session (TUI `/net on`, `/allow-dir`) without restart.

The jail builders themselves live in `session/isolation.py` (stdlib-only) so the
supervisor's PTY shell can share them without importing tools/.
"""
from __future__ import annotations

import fcntl
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from ..obs import get_logger
from ..session.isolation import (  # noqa: F401 — backend/os_sandbox_available are this module's public API
    _base_env,
    _docker,
    _linux_jail,
    _macos_jail,
    backend,
    os_sandbox_available,
)

_log = get_logger("runner")

DEFAULT_TIMEOUT = 30
_OUTPUT_CAP = 12000
_KILL_GRACE = 1.0    # seconds between SIGTERM and SIGKILL on timeout
_DRAIN_DEADLINE = 1.0  # bounded non-blocking pipe drain after the group is killed


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGTERM -> grace -> SIGKILL, to the whole process GROUP, then reap.

    `subprocess.run(timeout=)` kills only the leader; a grandchild keeps
    running (and keeps the stdout pipe open, blocking the reader forever —
    hermes scar #17327). Ordering discipline copied from server/pty.py
    PtyBridge.close: killpg returns EPERM for a group mid-exit on macOS, so
    fall back to signalling the leader directly.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = None
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if proc.poll() is not None:
            break
        try:
            if pgid is not None:
                os.killpg(pgid, sig)
            else:
                proc.send_signal(sig)
        except OSError:
            try:
                proc.send_signal(sig)
            except OSError:
                pass
        deadline = time.monotonic() + _KILL_GRACE
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
    try:
        proc.wait(timeout=_KILL_GRACE)
    except subprocess.TimeoutExpired:
        _log.error("terminal leader (pid %d) survived SIGKILL — abandoning, not blocking", proc.pid)


def _drain_nonblocking(stream, deadline: float) -> bytes:
    """Read whatever is immediately available from a pipe without ever blocking.

    Even after the group is killed, a descendant that escaped the group (e.g.
    a double-forked daemon) can hold the write end open — a blocking read
    would hang forever despite the timeout. O_NONBLOCK + a wall-clock deadline
    (the hermes _reconcile_local_exit drain shape).
    """
    if stream is None:
        return b""
    chunks: list[bytes] = []
    try:
        fd = stream.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    except (OSError, ValueError):
        return b""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        try:
            chunk = os.read(fd, 65536)
        except BlockingIOError:
            time.sleep(0.02)  # writer still alive; give it a beat, bounded
            continue
        except (OSError, ValueError):
            break
        if not chunk:
            break  # EOF — every writer is gone
        chunks.append(chunk)
    try:
        stream.close()
    except OSError:
        pass
    return b"".join(chunks)


def run_terminal(
    command: str,
    workspace: Path,
    *,
    isolation: str | None = None,
    allow_network: bool = False,
    writable_paths: "list[str] | tuple[str, ...]" = (),
    timeout: int = DEFAULT_TIMEOUT,
    workdir: str | None = None,
    image: str = "python:3.11-slim",
    memory_mb: int = 2048,
    cpus: float = 2,
) -> str:
    """Execute *command* in a shell under the active isolation mechanism."""
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    isolation = (isolation or backend()).lower()
    writable = [Path(p).resolve() for p in writable_paths]
    cwd = workspace
    if workdir:
        cand = (workspace / workdir).resolve() if not os.path.isabs(workdir) else Path(workdir).resolve()
        if isolation == "dir" or cand == workspace or workspace in cand.parents or cand in writable:
            cwd = cand

    note = ""
    if isolation == "docker" and shutil.which("docker"):
        cmd: list[str] = _docker(command, workspace, allow_network, image, memory_mb, cpus)
        run_cwd = None
    elif isolation == "sandbox" and os_sandbox_available():
        cmd = (_macos_jail if sys.platform == "darwin" else _linux_jail)(command, workspace, allow_network, writable)
        run_cwd = str(cwd) if sys.platform == "darwin" else None  # bwrap sets its own chdir
    else:
        if isolation != "dir":
            note = f"\n[lunamoth: '{isolation}' jail unavailable, ran with directory trust]"
        cmd = ["/bin/bash", "-c", command]
        run_cwd = str(cwd)

    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=run_cwd,
            env=_base_env(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,  # own process group so the timeout path can killpg it
        )
    except FileNotFoundError as e:
        _log.error("terminal runner unavailable (%s): %s", isolation, e)
        return f"[runner error: {e}]{note}"
    try:
        out_b, err_b = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _log.warning("terminal command timed out after %ds (%s): %.120s", timeout, isolation, command)
        _kill_group(proc)
        try:
            # The group is dead, so the pipes EOF immediately and this recovers
            # the partial output communicate() had already buffered. Bounded:
            # a descendant that escaped the group (setsid daemon) can still
            # hold the pipes open, hence the timeout + non-blocking fallback.
            out_b, err_b = proc.communicate(timeout=_DRAIN_DEADLINE)
        except subprocess.TimeoutExpired:
            out_b = _drain_nonblocking(proc.stdout, _DRAIN_DEADLINE)
            err_b = _drain_nonblocking(proc.stderr, _DRAIN_DEADLINE)
        parts = [f"[timed out after {timeout}s]"]
        out = out_b.decode("utf-8", errors="replace")[-_OUTPUT_CAP:].strip()
        err = err_b.decode("utf-8", errors="replace")[-2000:].strip()
        if out:
            parts.append(f"partial STDOUT:\n{out}")
        if err:
            parts.append(f"partial STDERR:\n{err}")
        return ("\n".join(parts) + note).strip()
    _log.info("terminal (%s, net=%s) exit=%d in %.1fs: %.120s",
              isolation, "on" if allow_network else "off", proc.returncode, time.monotonic() - t0, command)

    out = (out_b or b"").decode("utf-8", errors="replace")[-_OUTPUT_CAP:]
    err = (err_b or b"").decode("utf-8", errors="replace")[-2000:]
    parts = [f"exit={proc.returncode}"]
    if out:
        parts.append(f"STDOUT:\n{out}")
    if err:
        parts.append(f"STDERR:\n{err}")
    return ("\n".join(parts) + note).strip()
