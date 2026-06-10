"""The `lunamoth` command — Hermes-style CLI over named sessions.

    lunamoth                 attach the default session (first run: setup wizard)
    lunamoth new NAME        create a session (--isolation dir|sandbox|docker)
    lunamoth ls              list sessions
    lunamoth attach NAME     open a session in the TUI
    lunamoth rm NAME         delete a session
    lunamoth setup           (re)run the setup wizard for a session
    lunamoth update          update the installed checkout (git pull + uv sync)
    lunamoth doctor          check environment & sandbox backends
    lunamoth version         print version

Remote baseline: `ssh host -t lunamoth attach NAME`. Future gateways should
reuse `sessions.SessionMeta.env()` as the activation interface.

IMPORTANT: runtime modules (config/settings/tui) resolve paths from env at
import time, so this module only imports them lazily AFTER session env vars
are exported.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import runpy
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from . import sessions as S

APP_DIR = Path(__file__).resolve().parents[2]  # repo checkout (dev or ~/.lunamoth/app)
REPO_URL = "https://github.com/Lunamos/LunaMoth.git"

# session isolation level -> python tool execution backend
_ISOLATION_TO_BACKEND = {"dir": "local", "sandbox": "sandbox", "docker": "docker"}


def _activate(meta: S.SessionMeta) -> None:
    os.environ.update(meta.env())
    os.environ.setdefault("LUNAMOTH_PY_BACKEND", _ISOLATION_TO_BACKEND[meta.isolation])


def _needs_setup(meta: S.SessionMeta) -> bool:
    return not (meta.root / "config.json").exists()


def _launch_tui(meta: S.SessionMeta, args: argparse.Namespace) -> int:
    _activate(meta)
    if _needs_setup(meta):
        from .wizard import run_wizard

        run_wizard()
    argv = [sys.argv[0], "--cooldown", str(args.cooldown)]
    if args.forever and not args.plain:
        argv.append("--forever")  # plain terminal mode has thinking on by default
    if args.no_clean_on_exit:
        argv.append("--no-clean-on-exit")
    module = "lunamoth.terminal" if args.plain else "lunamoth.tui"
    meta.mark_running()
    old_argv = sys.argv
    try:
        sys.argv = argv
        runpy.run_module(module, run_name="__main__")
        return 0
    finally:
        sys.argv = old_argv
        meta.clear_running()


# ---- subcommands -----------------------------------------------------------


def cmd_default(args: argparse.Namespace) -> int:
    meta = S.ensure_default_session()
    return _launch_tui(meta, args)


def cmd_new(args: argparse.Namespace) -> int:
    try:
        meta = S.create_session(args.name, isolation=args.isolation, note=args.note)
    except (ValueError, FileExistsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"created session {meta.name!r} ({meta.isolation}) at {meta.root}")
    if args.attach:
        return _launch_tui(meta, args)
    print(f"start it with: lunamoth attach {meta.name}")
    return 0


def cmd_ls(_args: argparse.Namespace) -> int:
    rows = S.list_sessions()
    if not rows:
        print("no sessions yet — run `lunamoth` or `lunamoth new NAME`")
        return 0
    print(f"{'NAME':<18} {'ISOLATION':<10} {'STATUS':<10} LAST ACTIVE")
    for m in rows:
        pid = m.running_pid()
        status = f"up:{pid}" if pid else "idle"
        ts = m.last_active or m.created_at
        when = _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "-"
        print(f"{m.name:<18} {m.isolation:<10} {status:<10} {when}")
    return 0


def cmd_attach(args: argparse.Namespace) -> int:
    meta = S.load_session(args.name)
    if meta is None:
        print(f"error: no session named {args.name!r} (see `lunamoth ls`)", file=sys.stderr)
        return 1
    pid = meta.running_pid()
    if pid:
        print(f"error: session {args.name!r} already running (pid {pid})", file=sys.stderr)
        return 1
    return _launch_tui(meta, args)


def cmd_rm(args: argparse.Namespace) -> int:
    if not args.yes:
        try:
            ok = input(f"delete session {args.name!r} and its sandbox? [y/N] ").strip().lower() == "y"
        except EOFError:
            ok = False
        if not ok:
            print("aborted")
            return 1
    try:
        S.delete_session(args.name)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"deleted {args.name!r}")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    meta = S.load_session(args.name) or (S.ensure_default_session() if args.name == S.DEFAULT_SESSION else None)
    if meta is None:
        print(f"error: no session named {args.name!r}", file=sys.stderr)
        return 1
    _activate(meta)
    from .wizard import run_wizard

    run_wizard(non_interactive_ok=False)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    if not (APP_DIR / ".git").exists():
        print(f"error: {APP_DIR} is not a git checkout; reinstall via install.sh", file=sys.stderr)
        return 1
    git = shutil.which("git")
    if not git:
        print("error: git not found", file=sys.stderr)
        return 1
    if args.check:
        behind = _commits_behind()
        if behind is None:
            print("could not reach origin")
            return 1
        print("up to date" if behind == 0 else f"{behind} commit(s) behind — run `lunamoth update`")
        return 0
    print(f"updating {APP_DIR} ...")
    steps = [[git, "-C", str(APP_DIR), "pull", "--ff-only", "origin", "main"]]
    uv = shutil.which("uv") or str(S.lunamoth_home() / "bin" / "uv")
    if Path(uv).exists() or shutil.which("uv"):
        steps.append([uv, "sync", "--project", str(APP_DIR)])
    for cmd in steps:
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            print(f"error: {' '.join(map(str, cmd))} failed", file=sys.stderr)
            return proc.returncode
    _write_update_stamp(behind=0)
    print("updated.")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    def line(label: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✓' if ok else '✗'} {label}" + (f" — {detail}" if detail else ""))

    print(f"lunamoth {__version__} @ {APP_DIR}")
    line("python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0])
    line("uv", bool(shutil.which("uv")), shutil.which("uv") or "missing (install.sh provides one)")
    line("git checkout", (APP_DIR / ".git").exists(), "needed for `lunamoth update`")
    if sys.platform == "darwin":
        line("sandbox-exec (simple sandbox)", bool(shutil.which("sandbox-exec")))
    else:
        line("bubblewrap (simple sandbox)", bool(shutil.which("bwrap")), "install: apt/dnf install bubblewrap")
    line("docker (optional)", bool(shutil.which("docker")))
    print(f"  home: {S.lunamoth_home()}  sessions: {len(S.list_sessions())}")
    return 0


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"lunamoth {__version__}")
    return 0


# ---- update hint (cheap, cached, fail-silent) ------------------------------

_STAMP = "update_check.json"


def _commits_behind() -> int | None:
    git = shutil.which("git")
    if not git or not (APP_DIR / ".git").exists():
        return None
    try:
        subprocess.run(
            [git, "-C", str(APP_DIR), "fetch", "--quiet", "origin", "main"],
            timeout=5, check=True, capture_output=True,
        )
        out = subprocess.run(
            [git, "-C", str(APP_DIR), "rev-list", "--count", "HEAD..origin/main"],
            timeout=5, check=True, capture_output=True, text=True,
        )
        return int(out.stdout.strip())
    except Exception:
        return None


def _write_update_stamp(behind: int) -> None:
    try:
        S.lunamoth_home().mkdir(parents=True, exist_ok=True)
        (S.lunamoth_home() / _STAMP).write_text(json.dumps({"t": time.time(), "behind": behind}))
    except OSError:
        pass


def _maybe_update_hint() -> None:
    """At most once a day, mention available updates. Never blocks, never raises."""
    stamp = S.lunamoth_home() / _STAMP
    try:
        data = json.loads(stamp.read_text())
        if time.time() - data.get("t", 0) < 86400:
            if data.get("behind", 0) > 0:
                print(f"(update available: {data['behind']} commit(s) behind — `lunamoth update`)")
            return
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    behind = _commits_behind()
    if behind is None:
        return
    _write_update_stamp(behind)
    if behind > 0:
        print(f"(update available: {behind} commit(s) behind — `lunamoth update`)")


# ---- parser ----------------------------------------------------------------


def _add_tui_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--cooldown", type=float, default=2.0, help="idle self-talk pause seconds")
    p.add_argument("--forever", action="store_true", help="start with the idle self-talk loop ON")
    p.add_argument("--plain", action="store_true", help="legacy plain terminal instead of the TUI")
    p.add_argument("--no-clean-on-exit", action="store_true", help="keep the runtime sandbox on shutdown")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lunamoth", description="LunaMoth — agentic character tavern")
    p.add_argument("--version", action="version", version=f"lunamoth {__version__}")
    _add_tui_flags(p)
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("new", help="create a session")
    sp.add_argument("name")
    sp.add_argument("--isolation", choices=S.ISOLATION_LEVELS, default="sandbox")
    sp.add_argument("--note", default="")
    sp.add_argument("--attach", action="store_true", help="open it immediately")
    _add_tui_flags(sp)
    sp.set_defaults(func=cmd_new)

    sp = sub.add_parser("ls", aliases=["list"], help="list sessions")
    sp.set_defaults(func=cmd_ls)

    sp = sub.add_parser("attach", help="open a session in the TUI")
    sp.add_argument("name")
    _add_tui_flags(sp)
    sp.set_defaults(func=cmd_attach)

    sp = sub.add_parser("rm", help="delete a session")
    sp.add_argument("name")
    sp.add_argument("-y", "--yes", action="store_true")
    sp.set_defaults(func=cmd_rm)

    sp = sub.add_parser("setup", help="(re)run the setup wizard")
    sp.add_argument("name", nargs="?", default=S.DEFAULT_SESSION)
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser("update", help="update the installed checkout")
    sp.add_argument("--check", action="store_true", help="only check, do not install")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("doctor", help="check environment & sandbox backends")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("version", help="print version")
    sp.set_defaults(func=cmd_version)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        _maybe_update_hint()
        return cmd_default(args)
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
