"""Tool-loop guardrails (audit #24, the shape of hermes tool_guardrails.py):
identical failing calls warned at 2 and refused at 5; a tool with 8
consecutive failures (any args) is blocked until something succeeds or
reset_guardrails() runs. An unattended chara must not be able to spend a
night (and a key's budget) re-running the same failing call.
"""
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


class Counter:
    def __init__(self, exc=None):
        self.calls = 0
        self.exc = exc

    def __call__(self, **_kw):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return "fine"


def _audit_events(g):
    return [json.loads(line)["event"] for line in g.audit.path.read_text(encoding="utf-8").splitlines()]


def test_identical_failure_warns_at_2(gw, monkeypatch):
    monkeypatch.setattr(gw, "tool_terminal", Counter(ValueError("boom")))
    first = gw.call("terminal", command="x")
    assert first["ok"] is False and "loop guard" not in first["error"]
    second = gw.call("terminal", command="x")
    assert "loop guard" in second["error"] and "failed 2 times" in second["error"]


def test_different_args_are_different_signatures(gw, monkeypatch):
    monkeypatch.setattr(gw, "tool_terminal", Counter(ValueError("boom")))
    gw.call("terminal", command="x")
    other = gw.call("terminal", command="y")
    assert "loop guard" not in other["error"]  # not the same failing call


def test_identical_failure_refused_at_5(gw, monkeypatch):
    fail = Counter(ValueError("boom"))
    monkeypatch.setattr(gw, "tool_terminal", fail)
    for _ in range(4):
        gw.call("terminal", command="x")
    assert fail.calls == 4
    fifth = gw.call("terminal", command="x")
    assert fifth["ok"] is False and "refusing to run terminal" in fifth["error"]
    assert fail.calls == 4  # the 5th identical attempt never executed
    assert "tool_loop_refused" in _audit_events(gw)


def test_success_resets_the_exact_counter(gw, monkeypatch):
    failing = Counter(ValueError("boom"))
    monkeypatch.setattr(gw, "tool_terminal", failing)
    gw.call("terminal", command="x")
    monkeypatch.setattr(gw, "tool_terminal", Counter())  # now it succeeds
    assert gw.call("terminal", command="x")["ok"] is True
    monkeypatch.setattr(gw, "tool_terminal", Counter(ValueError("boom")))
    again = gw.call("terminal", command="x")
    assert "loop guard" not in again["error"]  # counter started over after the success


def test_tool_streak_blocks_after_8_consecutive_failures(gw, monkeypatch):
    fail = Counter(ValueError("boom"))
    monkeypatch.setattr(gw, "tool_terminal", fail)
    for i in range(8):  # different args each time: the exact-signature gate never trips
        out = gw.call("terminal", command=f"cmd-{i}")
        assert "refusing" not in out["error"] and "blocked" not in out["error"]
    assert fail.calls == 8
    ninth = gw.call("terminal", command="cmd-new")
    assert ninth["ok"] is False and "terminal is blocked" in ninth["error"]
    assert fail.calls == 8  # never executed


def test_any_success_resets_the_streak(gw, monkeypatch):
    fail = Counter(ValueError("boom"))
    monkeypatch.setattr(gw, "tool_terminal", fail)
    for i in range(7):
        gw.call("terminal", command=f"cmd-{i}")
    monkeypatch.setattr(gw, "tool_terminal", Counter())  # one success
    assert gw.call("terminal", command="ok")["ok"] is True
    fail2 = Counter(ValueError("boom"))
    monkeypatch.setattr(gw, "tool_terminal", fail2)
    out = gw.call("terminal", command="post-success")
    assert fail2.calls == 1 and "blocked" not in out["error"]  # streak started over


def test_streaks_are_per_tool(gw, monkeypatch):
    monkeypatch.setattr(gw, "tool_terminal", Counter(ValueError("boom")))
    for i in range(8):
        gw.call("terminal", command=f"cmd-{i}")
    assert gw.call("write_log", text="still works")["ok"] is True  # other tools unaffected


def test_reset_guardrails_clears_both_gates(gw, monkeypatch):
    fail = Counter(ValueError("boom"))
    monkeypatch.setattr(gw, "tool_terminal", fail)
    for i in range(8):
        gw.call("terminal", command="x" if i < 4 else f"cmd-{i}")
    assert "blocked" in gw.call("terminal", command="y")["error"]
    gw.reset_guardrails()  # the fresh-turn seam
    executed_before = fail.calls
    out = gw.call("terminal", command="x")
    assert fail.calls == executed_before + 1  # executes again
    assert "loop guard" not in out["error"] and "refusing" not in out["error"]


def test_refusals_do_not_compound_state(gw, monkeypatch):
    fail = Counter(ValueError("boom"))
    monkeypatch.setattr(gw, "tool_terminal", fail)
    for _ in range(4):
        gw.call("terminal", command="x")
    for _ in range(10):  # ten refusals must not advance the streak toward 8
        gw.call("terminal", command="x")
    out = gw.call("terminal", command="different")  # streak is still 4, so this runs
    assert fail.calls == 5
    assert "blocked" not in out["error"]


def test_denied_tools_count_as_failures_too(gw):
    # A model hammering a tool the pack denies is the same loop.
    for _ in range(4):
        out = gw.call("rest", minutes=5)
        assert "tool denied" in out["error"]
    fifth = gw.call("rest", minutes=5)
    assert "refusing to run rest" in fifth["error"]


def test_mcp_calls_are_guarded_too(gw):
    class DeadMcp:
        calls = 0

        def allowed_servers(self, entries):
            return ["srv"]

        def call(self, name, args):
            DeadMcp.calls += 1
            raise BrokenPipeError("server pipe closed")

    gw.mcp = DeadMcp()
    gw.set_enabled(["terminal"], ["srv"])
    for _ in range(4):
        gw.call("mcp__srv__fetch", url="http://x")
    assert DeadMcp.calls == 4
    fifth = gw.call("mcp__srv__fetch", url="http://x")
    assert "refusing to run mcp__srv__fetch" in fifth["error"]
    assert DeadMcp.calls == 4
