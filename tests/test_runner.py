
import pytest

from lunamoth.tools.runner import os_sandbox_available, run_terminal


def test_dir_runs_any_command(tmp_path):
    ws = tmp_path / "workspace"
    out = run_terminal("echo hello && echo world", ws, isolation="dir", timeout=10)
    assert "hello" in out and "world" in out and "exit=0" in out


def test_dir_writes_into_workspace(tmp_path):
    ws = tmp_path / "workspace"
    run_terminal("printf moth > art.txt", ws, isolation="dir", timeout=10)
    assert (ws / "art.txt").read_text() == "moth"


def test_timeout(tmp_path):
    ws = tmp_path / "workspace"
    out = run_terminal("sleep 5", ws, isolation="dir", timeout=1)
    assert "timed out" in out


def test_timeout_with_pipe_holding_grandchild_returns_and_kills_group(tmp_path):
    # The audit-#14 scar (hermes #17327): a background child inherits the
    # stdout pipe; with subprocess.run(timeout=) only the leader dies and the
    # post-timeout communicate() blocks until the grandchild exits (minutes).
    # The killpg path must return promptly AND leave no survivor.
    import subprocess
    import time

    ws = tmp_path / "workspace"
    marker = "47.1359"  # an unusual sleep duration we can pgrep for
    t0 = time.monotonic()
    out = run_terminal(f"sleep {marker} & sleep 60", ws, isolation="dir", timeout=1)
    assert time.monotonic() - t0 < 6  # bounded — not wedged on the held pipe
    assert "timed out after 1s" in out
    # The whole GROUP died, not just the leader: the background sleep is gone.
    deadline = time.monotonic() + 3
    alive = True
    while time.monotonic() < deadline:
        alive = subprocess.run(["pgrep", "-f", f"sleep {marker}"], capture_output=True).returncode == 0
        if not alive:
            break
        time.sleep(0.05)
    assert not alive


def test_timeout_keeps_partial_output(tmp_path):
    ws = tmp_path / "workspace"
    out = run_terminal("echo 早期输出; echo oops >&2; sleep 60", ws, isolation="dir", timeout=1)
    assert "timed out after 1s" in out
    assert "早期输出" in out  # what the command printed before the cut survives
    assert "oops" in out


def test_credentials_are_stripped(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    ws = tmp_path / "workspace"
    out = run_terminal('echo "key=$OPENAI_API_KEY"', ws, isolation="dir", timeout=10)
    assert "sk-secret" not in out


@pytest.mark.skipif(not os_sandbox_available(), reason="no OS sandbox (sandbox-exec/bwrap) on this host")
def test_sandbox_blocks_network_by_default(tmp_path):
    ws = tmp_path / "workspace"
    code = (
        "import urllib.request\n"
        "try:\n"
        "    urllib.request.urlopen('http://1.1.1.1', timeout=4); print('NETOK')\n"
        "except Exception: print('BLOCKED')\n"
    )
    out = run_terminal(f"python3 -c {_q(code)}", ws, isolation="sandbox", allow_network=False, timeout=20)
    assert "BLOCKED" in out and "NETOK" not in out


@pytest.mark.skipif(not os_sandbox_available(), reason="no OS sandbox on this host")
def test_sandbox_blocks_outside_write(tmp_path):
    ws = tmp_path / "workspace"
    target = tmp_path / "escape.txt"
    out = run_terminal(f"printf x > {target}", ws, isolation="sandbox", timeout=15)
    assert not target.exists()
    assert "exit=0" not in out  # the redirect should fail


def _q(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"
