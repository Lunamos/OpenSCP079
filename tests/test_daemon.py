import json
import os
import time

import pytest

from lunamoth import sessions as S
from lunamoth import cli


@pytest.fixture(autouse=True)
def temp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNAMOTH_HOME", str(tmp_path / "home"))
    yield


def _configure(meta):
    meta.config_path.write_text(json.dumps({"provider": "mock", "character_path": ""}), encoding="utf-8")


def test_status_progression():
    meta = S.create_session("a")
    assert meta.status() == "new"           # no config yet
    _configure(meta)
    assert S.load_session("a").status() == "idle"


def test_unconfigured_agent_does_not_daemonize():
    meta = S.create_session("b")
    assert cli._start_daemon(meta) is False
    assert meta.daemon_pid() is None


def test_daemon_start_and_stop():
    meta = S.create_session("c")
    _configure(meta)
    assert cli._start_daemon(meta, patience=5) is True
    pid = meta.daemon_pid()
    assert pid and pid > 0
    # the recorded pid is a live process
    os.kill(pid, 0)
    assert S.load_session("c").status() == "running"
    assert cli._stop_daemon(meta) is True
    time.sleep(0.5)
    assert meta.daemon_pid() is None


def test_start_all_only_configured(capsys):
    S.create_session("cfg"); _configure(S.load_session("cfg"))
    S.create_session("raw")  # unconfigured
    try:
        cli._start_all()
        running = {m.name for m in S.list_sessions() if m.daemon_pid()}
        assert "cfg" in running and "raw" not in running
    finally:
        for m in S.list_sessions():
            cli._stop_daemon(m)
