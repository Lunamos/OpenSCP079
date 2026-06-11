"""WebSocket transport for the JSON-RPC gateway."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..protocol import PROTOCOL_VERSION
from .dispatch import (
    JsonRpcDispatcher,
    error_response,
    hello_frame,
    ok_response,
    parse_error_response,
)

_log = logging.getLogger("lunamoth.server.ws")

_AUTH_TIMEOUT_SECONDS = 30.0
_WRITE_TIMEOUT_SECONDS = 10.0


def query_token(path: str | None) -> str:
    """Extract a token query parameter from a WebSocket request path."""

    if not path:
        return ""
    qs = parse_qs(urlsplit(path).query)
    vals = qs.get("token") or qs.get("auth") or []
    return str(vals[0]) if vals else ""


def query_auth_ok(path: str | None, expected_token: str) -> bool:
    token = query_token(path)
    return bool(token) and hmac.compare_digest(token, expected_token)


def auth_message_ok(raw: str, expected_token: str) -> tuple[bool, dict[str, Any] | None]:
    """Validate the first auth frame.

    Supports the JSON-RPC form
    `{"jsonrpc":"2.0","id":1,"method":"auth","params":{"token":"..."}}`
    and a small pre-protocol convenience form `auth TOKEN`.
    """

    line = raw.strip()
    if line.startswith("auth "):
        token = line[5:].strip()
        return (True, None) if hmac.compare_digest(token, expected_token) else (
            False,
            error_response(None, -32021, "authentication failed"),
        )
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return False, parse_error_response()
    rid = data.get("id") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("method") != "auth":
        return False, error_response(rid, -32020, "authentication required")
    params = data.get("params", {})
    if params is None:
        params = {}
    token = ""
    if isinstance(params, dict):
        token = str(params.get("token") or "")
    if not token:
        token = str(data.get("token") or "")
    if not token:
        return False, error_response(rid, -32602, "auth token is required")
    if not hmac.compare_digest(token, expected_token):
        return False, error_response(rid, -32021, "authentication failed")
    return True, ok_response(rid, {"ok": True, "protocol_version": PROTOCOL_VERSION}) if "id" in data else None


class _WSSink:
    def __init__(self, ws: Any, loop: asyncio.AbstractEventLoop):
        self._ws = ws
        self._loop = loop
        self._closed = False

    async def write_async(self, frame: dict[str, Any]) -> bool:
        if self._closed:
            return False
        try:
            await self._ws.send(json.dumps(frame, ensure_ascii=False))
            return True
        except Exception:
            self._closed = True
            _log.exception("websocket send failed")
            return False

    def write(self, frame: dict[str, Any]) -> bool:
        if self._closed:
            return False
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._loop.create_task(self.write_async(frame))
            return True
        fut = asyncio.run_coroutine_threadsafe(self.write_async(frame), self._loop)
        try:
            return bool(fut.result(timeout=_WRITE_TIMEOUT_SECONDS))
        except Exception:
            self._closed = True
            _log.exception("websocket threaded send failed")
            return False

    def close(self) -> None:
        self._closed = True


def _path_from_ws(ws: Any, fallback: str = "") -> str:
    request = getattr(ws, "request", None)
    if request is not None:
        path = getattr(request, "path", "")
        if path:
            return str(path)
    path = getattr(ws, "path", "")
    return str(path or fallback or "")


async def _recv_text(ws: Any) -> str:
    raw = await ws.recv()
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


async def _close_ws(ws: Any, code: int = 1000, reason: str = "") -> None:
    try:
        await ws.close(code=code, reason=reason)
    except Exception:
        _log.debug("websocket close failed", exc_info=True)


async def _authenticate(ws: Any, path: str, token: str) -> bool:
    if query_auth_ok(path, token):
        return True
    try:
        raw = await asyncio.wait_for(_recv_text(ws), timeout=_AUTH_TIMEOUT_SECONDS)
    except Exception:
        await _close_ws(ws, 4401, "authentication required")
        return False
    ok, response = auth_message_ok(raw, token)
    if response is not None:
        try:
            await ws.send(json.dumps(response, ensure_ascii=False))
        except Exception:
            return False
    if not ok:
        await _close_ws(ws, 4401, "authentication failed")
    return ok


async def _handle_connection(ws: Any, path: str, token: str) -> None:
    path = _path_from_ws(ws, path)
    if not await _authenticate(ws, path, token):
        return
    sink = _WSSink(ws, asyncio.get_running_loop())
    dispatch = JsonRpcDispatcher(sink.write)
    try:
        if not await sink.write_async(hello_frame()):
            return
        while True:
            try:
                line = (await _recv_text(ws)).strip()
            except Exception:
                break
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                if not await sink.write_async(parse_error_response()):
                    break
                continue
            resp = dispatch.dispatch(req)
            if resp is not None and not await sink.write_async(resp):
                break
            if dispatch.should_close:
                await _close_ws(ws, 1000, "detached")
                break
    finally:
        sink.close()
        dispatch.close()


async def serve_forever(host: str, port: int, token: str) -> None:
    """Run the optional WebSocket transport forever."""

    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("WebSocket transport requires websockets. Install with: uv sync --extra server") from exc

    active_client = False

    async def handler(ws: Any, path: str = "") -> None:
        nonlocal active_client
        if active_client:
            await _close_ws(ws, 4409, "another client is already connected")
            return
        active_client = True
        try:
            await _handle_connection(ws, path, token)
        finally:
            active_client = False

    async with websockets.serve(handler, host, int(port)):
        await asyncio.Future()
