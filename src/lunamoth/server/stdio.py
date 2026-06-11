"""Stdio transport for the JSON-RPC gateway."""
from __future__ import annotations

import json
import sys
import threading
from typing import Any, TextIO

from .dispatch import JsonRpcDispatcher, hello_frame, parse_error_response


class _StdoutFrames:
    def __init__(self, stream: TextIO):
        self._stream = stream
        self._lock = threading.Lock()

    def write(self, frame: dict[str, Any]) -> bool:
        line = json.dumps(frame, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                self._stream.write(line)
                self._stream.flush()
            except (BrokenPipeError, ValueError):
                return False
        return True


def serve() -> int:
    """Serve JSON-RPC on stdin/stdout until EOF, detach, or a broken pipe."""

    protocol_stdout = sys.stdout
    # Reserve stdout for JSON frames. Any accidental print from imported code is
    # kept off the protocol stream; diagnostics themselves are file-backed in obs/.
    sys.stdout = sys.stderr
    out = _StdoutFrames(protocol_stdout)
    dispatch = JsonRpcDispatcher(out.write)
    if not out.write(hello_frame()):
        dispatch.close()
        return 0
    try:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                if not out.write(parse_error_response()):
                    return 0
                continue
            resp = dispatch.dispatch(req)
            if resp is not None and not out.write(resp):
                return 0
            if dispatch.should_close:
                break
    finally:
        dispatch.close()
    return 0
