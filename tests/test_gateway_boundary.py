"""Tool dispatch exception boundary (audit #23): a crashing tool becomes an
error RESULT fed to the model + a tool_crash audit record — never a raw
traceback that aborts the whole streaming turn."""
import json

import pytest

from lunamoth.core.state import EnvState
from lunamoth.obs.audit import AuditLog
from lunamoth.tools.gateway import ToolGateway
from lunamoth.tools.sandbox import Sandbox


@pytest.fixture
def gw(tmp_path):
    g = ToolGateway(
        Sandbox(tmp_path / "sandbox"),
        EnvState(tmp_path / "env_status.json"),
        AuditLog(tmp_path / "audit.jsonl"),
    )
    g.set_enabled(["terminal", "write_log", "inspect_env"])
    return g


def _audit_events(g):
    return [json.loads(line)["event"] for line in g.audit.path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("exc", [BrokenPipeError("pipe gone"), OSError(24, "too many open files"), KeyError("missing")])
def test_untyped_tool_crash_becomes_error_result(gw, monkeypatch, exc):
    def boom(**_kw):
        raise exc

    monkeypatch.setattr(gw, "tool_terminal", boom)
    out = gw.call("terminal", command="ls")
    assert out["ok"] is False
    assert type(exc).__name__ in out["error"]  # visible, typed, never silent
    events = _audit_events(gw)
    assert "tool_crash" in events and "tool_call" in events


def test_typed_errors_keep_their_nicer_messages(gw, monkeypatch):
    def nope(**_kw):
        raise ValueError("minutes must be a number")

    monkeypatch.setattr(gw, "tool_terminal", nope)
    out = gw.call("terminal", command="x")
    assert out == {"ok": False, "error": "minutes must be a number"}
    assert "tool_crash" not in _audit_events(gw)  # typed branch, not a crash


def test_mcp_crash_is_contained_too(gw, monkeypatch, tmp_path):
    class FakeMcp:
        def allowed_servers(self, entries):
            return ["dead"]

        def call(self, name, args):
            raise BrokenPipeError("server pipe closed")

    gw.mcp = FakeMcp()
    gw.mcp_allowed = ["dead"]
    out = gw.call("mcp__dead__anything", text="x")
    assert out["ok"] is False and "BrokenPipeError" in out["error"]
    assert "tool_crash" in _audit_events(gw)


def test_keyboard_interrupt_still_propagates(gw, monkeypatch):
    def interrupt(**_kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(gw, "tool_terminal", interrupt)
    with pytest.raises(KeyboardInterrupt):
        gw.call("terminal", command="x")  # safety quit must never be swallowed
