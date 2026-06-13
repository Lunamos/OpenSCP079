"""Presence awareness: card-driven attach/detach prompts, the cross-process
handoff file, and the presence-gated request_permission tool."""
import pytest

from lunamoth.session.settings import Settings


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


def test_default_card_declares_presence_prompts(agent):
    a = agent()
    assert a.settings.user_name in a.attach_event_text()
    assert a.detach_event_text().strip()  # the card declares one; wording is its own


def test_card_without_prompts_means_no_events():
    from lunamoth.content.cards import CharacterCard
    from lunamoth import presence

    bare = CharacterCard(name="Visitor")
    assert presence.attach_text(bare, "Visitor", "op") == ""
    assert presence.detach_text(bare, "Visitor", "op") == ""


def test_presence_state_roundtrip(tmp_path):
    from lunamoth.presence import PresenceState

    p = PresenceState(tmp_path)
    assert p.first_meeting()
    p.mark_met()
    assert not p.first_meeting()
    assert p.pop_event() == ""
    p.queue_event("the operator left")
    assert p.pop_event() == "the operator left"
    assert p.pop_event() == ""  # consumed


def test_detach_queues_handoff_and_logs(agent):
    a = agent(toolpack="sandbox")
    session = a.make_session()
    a.note_detach(session)
    assert any(role == "system" for role, _ in session.context.pairs())
    assert a.presence.pop_event() != ""


def test_request_denied_when_operator_away(agent):
    a = agent(toolpack="sandbox")
    a.state.set_network(False)  # SANDBOX_ROOT is import-time global; reset shared state
    a.state.set_present(False)
    out = a.tools.call("request_permission", kind="network", reason="need pip")
    assert out["ok"] and "denied" in out["data"]
    assert a.state.load()["network_access"] is False


def test_request_granted_via_hook_when_present(agent):
    a = agent(toolpack="sandbox")
    a.state.set_present(True)
    asked = {}

    def approve(kind, reason, detail, wait_seconds):
        asked.update(kind=kind, reason=reason, wait=wait_seconds)
        return True

    a.tools.permission_hook = approve
    out = a.tools.call("request_permission", kind="network", reason="need pip", wait_seconds=30)
    assert out["ok"] and "granted" in out["data"]
    assert asked == {"kind": "network", "reason": "need pip", "wait": 30}
    assert a.state.load()["network_access"] is True


def test_request_denied_without_hook_even_when_present(agent):
    a = agent(toolpack="sandbox")
    a.state.set_network(False)  # SANDBOX_ROOT is import-time global; reset shared state
    a.state.set_present(True)
    a.tools.permission_hook = None
    out = a.tools.call("request_permission", kind="network", reason="x")
    assert out["ok"] and "denied" in out["data"]
    assert a.state.load()["network_access"] is False


def test_memory_grant_raises_budget(agent):
    a = agent(toolpack="sandbox")
    a.state.set_present(True)
    a.tools.permission_hook = lambda *args: True
    before = a.memory.limits.memory_chars
    out = a.tools.call("request_permission", kind="memory", reason="more room")
    assert out["ok"] and "granted" in out["data"]
    assert a.memory.limits.memory_chars > before


def test_mode_normalization():
    from lunamoth.presence import normalize_mode

    assert normalize_mode("live") == "live"
    assert normalize_mode("CHAT ") == "chat"
    # Pre-rename spellings map onto the two modes.
    assert normalize_mode("auto") == "live"
    assert normalize_mode("always") == "live"
    assert normalize_mode("off") == "chat"
    assert normalize_mode("banana") == "live"
    assert normalize_mode("") == "live"


def test_attach_never_wakes_a_resting_chara(agent):
    """Entering the room is presence bookkeeping only while the chara rests:
    no greeting, no arrival turn — a user MESSAGE is what wakes it."""
    import time as _time

    from lunamoth.protocol.api import CharaHandle

    a = agent()
    a.state.set_rest_until(_time.time() + 600)
    handle = CharaHandle(agent=a)
    info = handle.attach(present=True)
    assert info.opening == "none" and info.opening_text == ""
    assert a.state.load()["user_present"] is True


# ---- wordless visits leave no trace (owner decision 2026-06-13) -------------------

def test_drop_visit_tail_guards():
    from lunamoth.core.context import ContextBuffer

    c = ContextBuffer()
    c.add("user", "hi")
    mark = len(c.messages)
    c.add("system", "arrival", kind="visit")
    c.add("assistant", "hello there", kind="visit")
    assert c.drop_visit_tail(mark) == 2 and len(c.messages) == 1
    # refuses when a user message landed in the tail
    mark = len(c.messages)
    c.add("system", "arrival", kind="visit")
    c.add("user", "spoke")
    assert c.drop_visit_tail(mark) == 0
    # refuses when the tail is not a ceremony (protects the chara's own life)
    mark2 = len(c.messages)
    c.add("assistant", "musing on my own")
    assert c.drop_visit_tail(mark2) == 0
    # refuses when the buffer shrank past the mark (compaction)
    assert c.drop_visit_tail(len(c.messages) + 5) == 0


def test_wordless_visit_leaves_no_trace(agent):
    """Enter, watch, leave without a word: the arrival ceremony is rolled
    back, no departure note is added, no handoff is queued."""
    from lunamoth.protocol.api import CharaHandle

    a = agent()
    a.state.set_rest_until(0)  # SANDBOX_ROOT is import-time global; reset shared state
    a.presence.mark_met()  # not the first meeting -> arrival path, not first_mes
    handle = CharaHandle(agent=a)
    info = handle.attach(present=True)
    assert info.opening == "arrival" and info.opening_text
    before = len(handle._session.context.messages)
    list(handle.stream_event(info.opening_text))  # the client runs the arrival turn
    assert len(handle._session.context.messages) > before
    handle.detach()
    assert len(handle._session.context.messages) == before
    assert all(role != "system" or "visit" not in (m.get("kind") or "")
               for (role, _), m in zip(handle._session.context.pairs(), handle._session.context.messages))
    assert a.presence.pop_event() == ""  # no departure handoff


def test_spoken_visit_keeps_ceremony_and_departure(agent):
    from lunamoth.protocol.api import CharaHandle

    a = agent()
    a.state.set_rest_until(0)
    a.presence.mark_met()
    handle = CharaHandle(agent=a)
    info = handle.attach(present=True)
    list(handle.stream_event(info.opening_text))
    list(handle.stream_user("在吗？"))
    n_before_detach = len(handle._session.context.messages)
    handle.detach()
    msgs = handle._session.context.messages
    assert len(msgs) == n_before_detach + 1  # the on_detach line
    assert msgs[-1]["role"] == "system"
    assert a.presence.pop_event() != ""  # handoff queued as before


def test_visit_to_a_resting_chara_leaves_no_departure_note(agent):
    import time as _time

    from lunamoth.protocol.api import CharaHandle

    a = agent()
    a.state.set_rest_until(_time.time() + 600)
    handle = CharaHandle(agent=a)
    handle.attach(present=True)
    before = len(handle._session.context.messages)
    handle.detach()
    assert len(handle._session.context.messages) == before
    assert a.presence.pop_event() == ""


def test_reattach_does_not_replay_the_opening(agent):
    """A resident greets once per life, not once per page-load: the cached
    AttachInfo comes back with its opening neutered."""
    from lunamoth.protocol.api import CharaHandle
    from lunamoth.server.dispatch import JsonRpcDispatcher

    a = agent()
    a.state.set_rest_until(0)
    a.presence.mark_met()
    out = []
    d = JsonRpcDispatcher(out.append, handle=CharaHandle(agent=a))

    def opening(resp):
        res = resp["result"]
        return res["opening"] if isinstance(res, dict) else res.opening

    r1 = d.dispatch({"jsonrpc": "2.0", "id": 1, "method": "attach", "params": {}})
    assert opening(r1) == "arrival"
    r2 = d.dispatch({"jsonrpc": "2.0", "id": 2, "method": "attach", "params": {}})
    assert opening(r2) == "none"


def test_background_adopt_then_human_attach_still_greets(agent):
    """The supervisor pre-attaches a resident with present=False (idle driving)
    BEFORE the human connects. That background adopt must NOT eat the human's
    opener — the first present=True attach still greets (regression: the
    'greet once per life' change had neutered every human greeting)."""
    from lunamoth.protocol.api import CharaHandle

    a = agent()
    a.state.set_rest_until(0)
    handle = CharaHandle(agent=a)
    bg = handle.attach(present=False)          # daemon adopts first
    assert bg.opening == "none"
    human = handle.attach(present=True)        # the human arrives
    assert human.opening in ("greeting", "arrival", "probe")
    assert human.opening_text
    # a reconnect (second human attach) is presence-only, no re-greet
    again = handle.attach(present=True)
    assert again.opening == "none"


def test_reconnect_shows_the_conversation_so_far(agent):
    """A reconnect must restore the conversation that happened since the child
    started (regression: the dispatch cached the empty background-attach
    snapshot and replayed it forever)."""
    from lunamoth.protocol.api import CharaHandle

    a = agent()
    a.state.set_rest_until(0)
    handle = CharaHandle(agent=a)
    handle.attach(present=False)
    handle.attach(present=True)
    list(handle.stream_user("记住：项目代号 Moth"))   # a real exchange lands in context
    reattached = handle.attach(present=True)          # navigate away and back
    joined = " ".join(c for _, c in [(m.get("role"), m.get("content") or "")
                                     for m in [dict(x) for x in reattached.restored]])
    assert "项目代号 Moth" in joined
