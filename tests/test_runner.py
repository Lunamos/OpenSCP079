
import pytest

from lunamoth.runner import os_sandbox_available, run_terminal


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
