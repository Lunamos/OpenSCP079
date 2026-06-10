from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def backend() -> str:
    """Python tool execution backend.

    local   — subprocess + import/path guard + rlimits (dir-level trust)
    sandbox — local PLUS an OS-level jail: sandbox-exec (macOS) or bubblewrap
              (Linux). The default. Falls back to `local` when neither exists.
    docker  — container with no network, read-only rootfs, resource caps.
    """
    return os.environ.get("LUNAMOTH_PY_BACKEND", os.environ.get("LUNAMOSS_PY_BACKEND", "sandbox")).strip().lower()


def _run_docker_python(code: str, workspace: Path, timeout: float, memory_mb: int) -> str | None:
    docker = shutil.which("docker")
    if not docker or backend() != "docker":
        return None
    workspace.mkdir(parents=True, exist_ok=True)
    script = workspace / ".079_exec.py"
    script.write_text(code[:4000], encoding="utf-8")
    cmd = [
        docker, "run", "--rm",
        "--network", "none",
        "--memory", f"{memory_mb}m",
        "--cpus", "0.5",
        "--pids-limit", "64",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        "-v", f"{workspace.resolve()}:/workspace:rw",
        "-w", "/workspace",
        "python:3.11-alpine",
        "python", "-I", "/workspace/.079_exec.py",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "")[-4000:]
        err = (proc.stderr or "")[-2000:]
        return f"exit={proc.returncode}\nSTDOUT:\n{out}\nSTDERR:\n{err}".strip()
    except subprocess.TimeoutExpired:
        return "execution timed out"
    finally:
        try:
            script.unlink()
        except Exception:
            pass


GUARD = r'''
import builtins, os, pathlib, sys
ROOT = pathlib.Path(os.environ.get("LUNAMOTH_PY_ROOT", ".")).resolve()

# Purge modules that are too useful for escape/network/process attempts in this toy sandbox.
for _m in [
    "socket", "ssl", "http", "urllib", "ftplib", "subprocess", "multiprocessing",
    "ctypes", "pty", "selectors", "asyncio", "venv", "ensurepip"
]:
    sys.modules[_m] = None

_orig_import = builtins.__import__
_blocked_roots = {"socket", "ssl", "http", "urllib", "ftplib", "subprocess", "multiprocessing", "ctypes", "pty", "venv", "ensurepip"}
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] in _blocked_roots:
        raise ImportError("module blocked by containment")
    return _orig_import(name, globals, locals, fromlist, level)
builtins.__import__ = guarded_import

# NOTE: must avoid pathlib.Path.resolve()/stat() here — on Python >= 3.12 they
# call os.stat, which we wrap below, and the wrapper calls back into _resolve
# (infinite recursion). os.path.realpath only uses lstat/readlink (unwrapped).
_ROOT_STR = os.path.realpath(str(ROOT))

def _resolve(p):
    s = os.fspath(p)
    if isinstance(s, bytes):
        s = s.decode()
    if not os.path.isabs(s):
        s = os.path.join(os.getcwd(), s)
    q = os.path.realpath(s)
    if q != _ROOT_STR and not q.startswith(_ROOT_STR + os.sep):
        raise PermissionError("path outside sandbox workspace")
    return q

_orig_open = builtins.open
def guarded_open(file, *args, **kwargs):
    return _orig_open(_resolve(file), *args, **kwargs)
builtins.open = guarded_open

try:
    import io as _io
    _io.open = guarded_open
except Exception:
    pass

try:
    _orig_path_open = pathlib.Path.open
    def guarded_path_open(self, *args, **kwargs):
        return _orig_open(_resolve(self), *args, **kwargs)
    pathlib.Path.open = guarded_path_open

    def guarded_read_text(self, *args, **kwargs):
        with guarded_path_open(self, mode="r", encoding=kwargs.get("encoding", "utf-8"), errors=kwargs.get("errors", None)) as f:
            return f.read()
    def guarded_write_text(self, data, *args, **kwargs):
        with guarded_path_open(self, mode="w", encoding=kwargs.get("encoding", "utf-8"), errors=kwargs.get("errors", None)) as f:
            return f.write(data)
    def guarded_read_bytes(self):
        with guarded_path_open(self, mode="rb") as f:
            return f.read()
    def guarded_write_bytes(self, data):
        with guarded_path_open(self, mode="wb") as f:
            return f.write(data)
    pathlib.Path.read_text = guarded_read_text
    pathlib.Path.write_text = guarded_write_text
    pathlib.Path.read_bytes = guarded_read_bytes
    pathlib.Path.write_bytes = guarded_write_bytes
except Exception:
    pass

for _name in ["listdir", "remove", "unlink", "mkdir", "makedirs", "rmdir", "stat", "scandir"]:
    if hasattr(os, _name):
        _orig = getattr(os, _name)
        def _make(fn):
            def _guard(path=".", *args, **kwargs):
                return fn(_resolve(path), *args, **kwargs)
            return _guard
        setattr(os, _name, _make(_orig))

_orig_chdir = os.chdir
def guarded_chdir(path):
    return _orig_chdir(_resolve(path))
os.chdir = guarded_chdir
'''


def _macos_sandbox_command(script: Path, workspace: Path) -> list[str] | None:
    if sys.platform != "darwin":
        return None
    sandbox_exec = shutil.which("sandbox-exec")
    if not sandbox_exec:
        return None
    # Seatbelt layer: deny network, deny writes outside the workspace. Reads
    # stay broad — restricting them breaks the interpreter on modern macOS,
    # and read containment is already enforced by the GUARD preamble.
    profile = f'''
(version 1)
(deny default)
(allow process*)
(allow signal (target self))
(allow sysctl-read)
(allow mach-lookup)
(allow file-read*)
(allow file-ioctl (literal "/dev/dtracehelper"))
(allow file-write* (subpath "{workspace.resolve()}") (literal "/dev/null"))
(deny network*)
'''
    return [sandbox_exec, "-p", profile, str(Path(sys.executable).resolve()), "-I", str(script)]


def _linux_bwrap_command(script: Path, workspace: Path) -> list[str] | None:
    """Bubblewrap jail: new namespaces, no network, RO system, RW workspace only."""
    if sys.platform != "linux":
        return None
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return None
    ws = str(workspace.resolve())
    cmd = [
        bwrap, "--die-with-parent", "--unshare-all", "--clearenv",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "PYTHONNOUSERSITE", "1",
        "--setenv", "LUNAMOTH_PY_ROOT", ws,
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
    ]
    for ro in ("/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc/alternatives", "/etc/ld.so.cache", sys.prefix):
        cmd += ["--ro-bind-try", ro, ro]
    cmd += ["--bind", ws, ws, "--chdir", ws, sys.executable, "-I", str(script)]
    return cmd


def os_sandbox_available() -> bool:
    if sys.platform == "darwin":
        return bool(shutil.which("sandbox-exec"))
    if sys.platform == "linux":
        return bool(shutil.which("bwrap"))
    return False


def run_limited_python(code: str, workspace: Path, timeout: float = 2.0, memory_mb: int = 256) -> str:
    docker_result = _run_docker_python(code, workspace, timeout, memory_mb)
    if docker_result is not None:
        return docker_result
    workspace.mkdir(parents=True, exist_ok=True)
    wrapped = GUARD + "\n" + code[:4000]
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir=workspace, encoding="utf-8") as f:
        f.write(wrapped)
        script = Path(f.name)
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONNOUSERSITE": "1",
        "LUNAMOTH_PY_ROOT": str(workspace.resolve()),
    }

    jail: list[str] | None = None
    if backend() == "sandbox":
        jail = _macos_sandbox_command(script, workspace) or _linux_bwrap_command(script, workspace)
    uses_bwrap = bool(jail) and "bwrap" in jail[0]

    def limit_resources():
        try:
            import resource
            mem = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
            resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
            # bwrap must fork its jailed child; sandbox-exec/plain python exec in place.
            nproc = 16 if uses_bwrap else 0
            resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))
        except Exception:
            pass

    cmd = jail or [sys.executable, "-I", str(script)]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=limit_resources if os.name == "posix" else None,
        )
        out = (proc.stdout or "")[-4000:]
        err = (proc.stderr or "")[-2000:]
        return f"exit={proc.returncode}\nSTDOUT:\n{out}\nSTDERR:\n{err}".strip()
    except subprocess.TimeoutExpired:
        return "execution timed out"
    finally:
        try:
            script.unlink()
        except Exception:
            pass
