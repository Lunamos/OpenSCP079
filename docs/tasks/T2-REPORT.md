# T2 report — server gateway

## What works

- Added `lunamoth serve NAME --stdio` as a newline-delimited JSON-RPC 2.0 gateway over stdin/stdout.
- Added `lunamoth serve NAME --host 127.0.0.1 --port 8137 [--token TOKEN]` as the same dispatch over WebSocket.
- Both transports share `src/lunamoth/server/dispatch.py`.
- The server hosts exactly one activated session per process: `front/cli.py` exports the session env before importing the runtime-backed server modules.
- Handshake sends a `hello` notification with `protocol_version: 1`.
- Request methods implemented: `attach`, `send`, `idle`, `interrupt`, `command`, `snapshot`, `permission_reply`, `detach`.
- Stream events are pushed as `event` notifications using `protocol.codec.to_dict` verbatim.
- Permission requests are pushed as `permission_ask` notifications and answered by `permission_reply`; timeout/interrupt denies.
- WebSocket auth accepts either `?token=...`/`?auth=...` or a first `auth` message. If `--token` is omitted, a token is generated and printed once at startup.
- One-client v1 behavior is enforced: a second WS connection is closed, and a repeated in-connection `attach` gets a JSON-RPC error.

## How to try it

Stdio:

```bash
uv run lunamoth serve home --stdio
```

Then write one JSON object per line, for example:

```json
{"jsonrpc":"2.0","id":1,"method":"attach","params":{"present":true}}
{"jsonrpc":"2.0","id":2,"method":"send","params":{"text":"status"}}
{"jsonrpc":"2.0","id":3,"method":"detach","params":{}}
```

WebSocket:

```bash
uv sync --extra server
uv run lunamoth serve home --host 127.0.0.1 --port 8137
```

Use the generated token printed on stderr, either as `ws://127.0.0.1:8137/?token=TOKEN` or as the first JSON-RPC message:

```json
{"jsonrpc":"2.0","id":1,"method":"auth","params":{"token":"TOKEN"}}
```

## Verification notes

- Direct dispatch tests cover attach→send streaming, command, snapshot, interrupt, permission ask/reply, attach rejection, and WebSocket auth helpers.
- `tests/test_architecture.py` remains green: `server/` does not import `front/`, Textual, or Rich.
- Baseline `uv sync && uv run python -m pytest -q` was not green in this worktree before code changes: `pytest` is only in the `dev` extra, and with this shell's `LC_ALL=C.UTF-8` the default-card tests choose the English bundled card while existing tests assert the Chinese card. I used `uv sync --extra dev` for test installation and `LUNAMOTH_LANG=zh` for the full test run.

## Deferred

- No frontend client has been moved onto the remote gateway yet; this task only adds the gateway seam.
- Multi-chara hosting remains out of scope and should be one subprocess per chara later.
- No real network end-to-end WebSocket test was added; auth is unit-tested to avoid flakiness.
