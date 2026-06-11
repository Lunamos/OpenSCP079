"""`lunamoth desktop` — one local process serving the desktop renderer.

Three small parts, copied from Hermes Desktop's shape (thin shell, one gateway,
clients reuse the per-session protocol):

- a static HTTP server for the web renderer (`front/web/`, no build step), plus
  a tiny card-upload endpoint for drag-and-drop imports;
- a WebSocket endpoint with two path roles:
    /hub            board-level JSON-RPC (hub.HubDispatcher)
    /chara/<name>   a byte-level pipe to a child `lunamoth serve <name> --stdio`
                    process — the existing per-session gateway, unchanged;
- daemon adopt/handback: opening a chat pauses the chara's background daemon,
  closing it resumes the background life (same dance as attaching the TUI).

Everything binds 127.0.0.1 and requires the launch token.
"""
from __future__ import annotations

import asyncio
import functools
import http.server
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..config import ROOT
from ..session import sessions as S
from . import hub as H
from .ws import _WSSink, _close_ws, _path_from_ws, _recv_text, query_auth_ok

_log = logging.getLogger("lunamoth.server.desktop")

WEB_DIR = Path(__file__).resolve().parents[1] / "front" / "web"

_ISOLATION_TO_BACKEND = {"dir": "local", "sandbox": "sandbox", "docker": "docker"}

_UPLOAD_MAX = 8 * 1024 * 1024  # SillyTavern PNG cards are usually < 2 MB


# ---- static HTTP (renderer assets + card upload) ----------------------------------

class _WebHandler(http.server.SimpleHTTPRequestHandler):
    token = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet by default
        _log.debug("http: " + fmt, *args)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        url = urlsplit(self.path)
        if url.path != "/upload":
            self.send_error(404)
            return
        qs = parse_qs(url.query)
        token = (qs.get("token") or [""])[0]
        if not self.token or token != self.token:
            self.send_error(403)
            return
        length = int(self.headers.get("Content-Length") or 0)
        name = Path(self.headers.get("X-Filename") or "card.json").name
        if length <= 0 or length > _UPLOAD_MAX or Path(name).suffix.lower() not in (".json", ".png"):
            self.send_error(400, "expected a .json or .png card under 8 MB")
            return
        body = self.rfile.read(length)
        base = H.user_cards_dir()
        base.mkdir(parents=True, exist_ok=True)
        target = base / name
        n = 2
        while target.exists():
            target = base / f"{Path(name).stem}-{n}{Path(name).suffix}"
            n += 1
        target.write_bytes(body)
        payload = json.dumps({"path": str(target)}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _start_http(host: str, port: int, token: str) -> http.server.ThreadingHTTPServer:
    handler = type("Handler", (_WebHandler,), {"token": token})
    server = http.server.ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, name="desktop-http", daemon=True)
    thread.start()
    return server


# ---- per-chara child gateway proxy -------------------------------------------------

class _CharaProxy:
    """Pipe one WebSocket client to one `lunamoth serve <name> --stdio` child."""

    def __init__(self, meta: S.SessionMeta):
        self.meta = meta
        self.was_live = False
        self.proc: asyncio.subprocess.Process | None = None

    async def start(self) -> str:
        """Spawn the child gateway; returns '' on success or a human error."""
        meta = self.meta
        if not meta.is_configured():
            return "chara is not set up yet"
        if meta.running_pid():
            return "another frontend is attached to this chara"
        if meta.daemon_pid():
            self.was_live = True
            H.stop_daemon(meta)
            for _ in range(40):  # the daemon needs a moment to let go of the session
                if not meta.daemon_pid():
                    break
                await asyncio.sleep(0.1)
        env = {**os.environ, **meta.env()}
        env.setdefault("LUNAMOTH_PY_BACKEND", _ISOLATION_TO_BACKEND[meta.isolation])
        log = (meta.root / "desktop.log").open("ab")
        try:
            self.proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "lunamoth.front.cli", "serve", meta.name, "--stdio",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=log, env=env, cwd=str(ROOT),
            )
        finally:
            log.close()
        return ""

    async def pump(self, ws: Any) -> None:
        """Bidirectional pipe until either side closes."""
        proc = self.proc
        assert proc is not None and proc.stdout is not None and proc.stdin is not None

        async def child_to_ws() -> None:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    await ws.send(line.decode("utf-8", errors="replace").rstrip("\n"))
                except Exception:  # noqa: BLE001 - client went away
                    break

        async def ws_to_child() -> None:
            while True:
                try:
                    raw = await _recv_text(ws)
                except Exception:  # noqa: BLE001 - client went away
                    break
                try:
                    proc.stdin.write(raw.encode("utf-8") + b"\n")
                    await proc.stdin.drain()
                except (ConnectionResetError, BrokenPipeError):
                    break

        tasks = [asyncio.create_task(child_to_ws()), asyncio.create_task(ws_to_child())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()

    async def stop(self) -> None:
        proc = self.proc
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=8.0)
            except asyncio.TimeoutError:
                proc.kill()
        # Hand the chara back to its background life.
        if self.was_live:
            meta = S.load_session(self.meta.name)
            if meta is not None and meta.is_configured():
                await asyncio.to_thread(H.start_daemon, meta)


# ---- WebSocket routing ---------------------------------------------------------------

_active_charas: dict[str, _CharaProxy] = {}
_chara_lock = asyncio.Lock()


async def _handle_hub(ws: Any) -> None:
    sink = _WSSink(ws, asyncio.get_running_loop())
    dispatcher = H.HubDispatcher(sink.write)
    loop = asyncio.get_running_loop()
    try:
        await sink.write_async({"jsonrpc": "2.0", "method": "hello", "params": {"role": "hub"}})
        while True:
            try:
                raw = await _recv_text(ws)
            except Exception:  # noqa: BLE001
                break
            line = raw.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                await sink.write_async({"jsonrpc": "2.0", "id": None,
                                        "error": {"code": -32700, "message": "parse error"}})
                continue
            # Handlers may block on provider HTTP (key test / transcribe): run each
            # request off the loop so the connection stays responsive.
            loop.create_task(_dispatch_async(dispatcher, req, sink))
    finally:
        sink.close()


async def _dispatch_async(dispatcher: H.HubDispatcher, req: Any, sink: _WSSink) -> None:
    resp = await asyncio.to_thread(dispatcher.dispatch, req)
    if resp is not None:
        await sink.write_async(resp)


async def _handle_chara(ws: Any, name: str) -> None:
    meta = S.load_session(name)
    if meta is None:
        await _close_ws(ws, 4404, "no such chara")
        return
    async with _chara_lock:
        if name in _active_charas:
            await _close_ws(ws, 4409, "this chara already has a desktop client")
            return
        proxy = _CharaProxy(meta)
        _active_charas[name] = proxy
    try:
        err = await proxy.start()
        if err:
            await _close_ws(ws, 4423, err)
            return
        await proxy.pump(ws)
    finally:
        await proxy.stop()
        async with _chara_lock:
            _active_charas.pop(name, None)
        await _close_ws(ws)


async def _handler(ws: Any, path: str, token: str) -> None:
    path = _path_from_ws(ws, path)
    if not query_auth_ok(path, token):
        await _close_ws(ws, 4401, "authentication required")
        return
    route = urlsplit(path).path
    if route in ("", "/", "/hub"):
        await _handle_hub(ws)
    elif route.startswith("/chara/"):
        await _handle_chara(ws, route[len("/chara/"):].strip("/"))
    else:
        await _close_ws(ws, 4404, "unknown endpoint")


# ---- entry --------------------------------------------------------------------------

def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


async def _serve_ws(host: str, port: int, token: str) -> None:
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - optional extra
        raise RuntimeError("the desktop needs websockets. Install with: uv sync --extra server") from exc
    handler = functools.partial(_ws_entry, token=token)
    async with websockets.serve(handler, host, port, max_size=16 * 1024 * 1024):
        await asyncio.Future()


async def _ws_entry(ws: Any, path: str = "", *, token: str) -> None:
    await _handler(ws, path, token)


def serve_desktop(host: str, http_port: int, ws_port: int, token: str,
                  open_browser: bool = True) -> int:
    if not WEB_DIR.is_dir():
        print(f"error: renderer assets missing at {WEB_DIR}", file=sys.stderr)
        return 1
    httpd = _start_http(host, http_port, token)
    url = f"http://{host}:{http_port}/#token={token}&ws={ws_port}"
    print(f"LunaMoth desktop: {url}", file=sys.stderr, flush=True)
    if open_browser:
        def _open() -> None:
            time.sleep(0.4)
            if sys.platform == "darwin":
                subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import webbrowser

                webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()
    try:
        asyncio.run(_serve_ws(host, ws_port, token))
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
    return 0
