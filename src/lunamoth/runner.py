"""Run shell commands for the agent's `terminal` tool — Hermes/Claude-Code style.

The agent is given ONE language-agnostic capability: run a shell command in its
session workspace. Containment is provided by the OS, not by intercepting a
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
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_TIMEOUT = 30
_OUTPUT_CAP = 12000

# Don't hand the agent our own provider/credentials through the environment.
_ENV_BLOCKLIST = (
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN", "LLM_PROVIDER",
)


def backend() -> str:
    """Isolation mechanism for this session (LUNAMOTH_PY_BACKEND: dir|sandbox|docker)."""
    raw = os.environ.get("LUNAMOTH_PY_BACKEND", os.environ.get("LUNAMOSS_PY_BACKEND", "sandbox")).strip().lower()
    return "dir" if raw in {"dir", "local"} else raw


def os_sandbox_available() -> bool:
    if sys.platform == "darwin":
        return bool(shutil.which("sandbox-exec"))
    if sys.platform == "linux":
        return bool(shutil.which("bwrap"))
    return False


def _base_env(workspace: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _ENV_BLOCKLIST}
    env["TMPDIR"] = str(workspace)  # keep temp files inside the writable jail
    env.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin")
    return env


def _macos_jail(command: str, workspace: Path, allow_network: bool, writable: list[Path]) -> list[str]:
    writes = "\n".join(f'(allow file-write* (subpath "{p}"))' for p in [workspace, *writable])
    net = "(allow network*)" if allow_network else "(deny network*)"
    profile = f'''
(version 1)
(deny default)
(allow process*)
(allow signal (target self))
(allow sysctl-read)
(allow mach-lookup)
(allow file-read*)
(allow file-ioctl (literal "/dev/dtracehelper") (literal "/dev/tty"))
{writes}
(allow file-write* (literal "/dev/null") (literal "/dev/tty") (literal "/dev/stdout") (literal "/dev/stderr"))
{net}
'''
    return ["sandbox-exec", "-p", profile, "/bin/bash", "-c", command]


def _linux_jail(command: str, workspace: Path, allow_network: bool, writable: list[Path]) -> list[str]:
    ws = str(workspace)
    cmd = ["bwrap", "--die-with-parent", "--unshare-all"]
    if allow_network:
        cmd += ["--share-net", "--ro-bind-try", "/etc/resolv.conf", "/etc/resolv.conf"]
    cmd += ["--proc", "/proc", "--dev", "/dev"]
    for ro in ("/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc", sys.prefix):
        cmd += ["--ro-bind-try", ro, ro]
    cmd += ["--bind", ws, ws]
    for p in writable:
        cmd += ["--bind", str(p), str(p)]
    cmd += ["--chdir", ws, "/bin/bash", "-c", command]
    return cmd


def _docker(command: str, workspace: Path, allow_network: bool, image: str, memory_mb: int, cpus: float) -> list[str]:
    # NOTE: disk isn't hard-capped here — the container is read-only except the
    # bind-mounted workspace (host disk). A hard quota needs --storage-opt, which
    # only some drivers accept; we skip it rather than risk failing to launch.
    return [
        "docker", "run", "--rm", "-i",
        "--network", "bridge" if allow_network else "none",
        "--memory", f"{memory_mb}m", "--cpus", str(cpus), "--pids-limit", "256",
        "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=256m",
        "-v", f"{workspace}:/workspace:rw", "-w", "/workspace",
        image, "sh", "-c", command,
    ]


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

    try:
        proc = subprocess.run(
            cmd,
            cwd=run_cwd,
            env=_base_env(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            start_new_session=True,  # own process group so timeout kills children
        )
    except subprocess.TimeoutExpired:
        return f"[timed out after {timeout}s]{note}"
    except FileNotFoundError as e:
        return f"[runner error: {e}]{note}"

    out = (proc.stdout or "")[-_OUTPUT_CAP:]
    err = (proc.stderr or "")[-2000:]
    parts = [f"exit={proc.returncode}"]
    if out:
        parts.append(f"STDOUT:\n{out}")
    if err:
        parts.append(f"STDERR:\n{err}")
    return ("\n".join(parts) + note).strip()
