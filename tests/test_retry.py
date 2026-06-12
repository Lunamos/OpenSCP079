"""Failure policy: retry 5x at 5s (Claude-Code style), then surface the error.
There is NO fabricated fallback output anywhere — a failed request fails."""
import urllib.error
import urllib.request

import pytest

from lunamoth.config import LLMConfig
from lunamoth.core.llm import LLMClient
from lunamoth.session.settings import Settings


def _client():
    return LLMClient(LLMConfig(provider="openai_compatible", base_url="https://x.test/v1", model="m"))


def _drive(gen):
    """Drive the connect generator; return (yielded notices, return value)."""
    notices = []
    try:
        while True:
            notices.append(next(gen))
    except StopIteration as stop:
        return notices, stop.value


@pytest.fixture
def no_sleep(monkeypatch):
    import lunamoth.core.llm as llm_mod

    monkeypatch.setattr(llm_mod.time, "sleep", lambda _s: None)


def test_transient_failure_retries_then_succeeds(monkeypatch, no_sleep):
    calls = {"n": 0}

    def flaky(req, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("connection reset")
        return "RESPONSE"

    monkeypatch.setattr(urllib.request, "urlopen", flaky)
    notices, resp = _drive(_client()._connect_with_retry("https://x.test/v1/chat/completions", b"{}", 1))
    assert resp == "RESPONSE"
    # Retries surface as typed Notice events (frontends render them dimmed).
    assert len(notices) == 2 and all(n.kind == "retry" and "retry" in n.text for n in notices)


def test_gives_up_after_five_retries(monkeypatch, no_sleep):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    gen = _client()._connect_with_retry("https://x.test/v1/chat/completions", b"{}", 1)
    with pytest.raises(RuntimeError, match="gave up after 5 retries"):
        _drive(gen)


def test_permanent_http_error_surfaces_immediately(monkeypatch, no_sleep):
    class Fake401(urllib.error.HTTPError):
        def __init__(self):
            super().__init__("https://x.test", 401, "unauthorized", {}, None)

        def read(self):
            return b'{"error": "bad key"}'

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: (_ for _ in ()).throw(Fake401()))
    gen = _client()._connect_with_retry("https://x.test/v1/chat/completions", b"{}", 1)
    with pytest.raises(RuntimeError, match="HTTP 401"):
        _drive(gen)  # no retries for auth errors — surface NOW


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LUNAMOTH_SANDBOX", str(tmp_path / "sandbox"))
    monkeypatch.setenv("LUNAMOTH_CONFIG_DIR", str(tmp_path / "cfg"))
    from lunamoth.core.agent import LunaMothAgent

    def make(**kw):
        kw.setdefault("toolpack", "")
        return LunaMothAgent(Settings(character_path="", **kw))

    return make


def test_idle_cycle_failure_surfaces_without_fallback(agent, monkeypatch):
    a = agent()
    a.transcript.reset()
    s = a.make_session()

    def broken_stream(*_args, **_kw):
        def gen():
            raise RuntimeError("HTTP 500: upstream died — gave up after 5 retries")
            yield  # pragma: no cover (makes this a generator)

        return gen()

    monkeypatch.setattr(a, "_reply_stream", broken_stream)
    with pytest.raises(RuntimeError, match="upstream died"):
        list(a.stream_think(s))
    # No fabricated "cycle 0042: buffer stable" output ever enters the context.
    assert all(m.get("kind") != "think" for m in s.context.messages)


# ---- empty-completion detection (audit #4) ---------------------------------------------
# A stream ending with no content, no tool calls and no finish_reason used to
# record assistant {content: None} and end the turn SILENTLY — an invisible
# non-answer. Now: bounded retry, then a visible error.


def _patch_turns(monkeypatch, turns):
    """Each entry: (text, tool_calls, thinking, finish). Pops one per call."""
    from lunamoth.core.llm import LLMClient

    def fake_stream_turn(self, messages, tools, text_out, reasoning=None, channel="say"):
        text, tool_calls, thinking, finish = turns.pop(0)
        if text:
            text_out.append(text)
        return (tool_calls, thinking, finish)
        yield  # pragma: no cover — makes this a generator (yield from compatible)

    monkeypatch.setattr(LLMClient, "_stream_turn", fake_stream_turn)


def _agent_events(client, record=None):
    return list(client.stream_agent("hi", [], ["sys"], [], tools=None, execute=lambda tc: {}, record=record))


def test_truly_empty_stream_retries_then_raises_visibly(monkeypatch, no_sleep):
    _patch_turns(monkeypatch, [("", [], "", "")] * 4)  # empty forever
    recorded = []
    with pytest.raises(RuntimeError, match="empty stream"):
        _agent_events(_client(), record=recorded.append)
    # Nothing fabricated, nothing silently recorded: no assistant {content: None}.
    assert all(m.get("content") is not None for m in recorded)


def test_empty_retry_notices_are_visible(monkeypatch, no_sleep):
    from lunamoth.protocol import Notice

    _patch_turns(monkeypatch, [("", [], "", "")] * 4)
    events = []
    try:
        for ev in _client().stream_agent("hi", [], ["sys"], [], tools=None, execute=lambda tc: {}):
            events.append(ev)
    except RuntimeError:
        pass
    retries = [e for e in events if isinstance(e, Notice) and e.kind == "retry"]
    assert len(retries) == 3  # every retry is announced, never silent


def test_reasoning_only_exhaustion_is_distinguished(monkeypatch, no_sleep):
    _patch_turns(monkeypatch, [("", [], "long private thinking", "stop")] * 4)
    with pytest.raises(RuntimeError, match="reasoning-only.*thinking exhausted"):
        _agent_events(_client())


def test_empty_then_real_reply_recovers(monkeypatch, no_sleep):
    _patch_turns(monkeypatch, [("", [], "", ""), ("", [], "", ""), ("here.", [], "", "stop")])
    recorded = []
    _agent_events(_client(), record=recorded.append)  # no exception
    assert recorded and recorded[-1]["content"] == "here."  # the recovered turn is committed
