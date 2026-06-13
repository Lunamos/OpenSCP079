"""The in-process messaging host shares the serve child's ONE agent.

A WeChat message must (a) run a turn on the dispatcher's handle, (b) stream that
turn's events onto the transport (so the desktop app sees it live), and (c)
deliver only the say-channel text back to the adapter.
"""
from __future__ import annotations

from lunamoth.messaging.base import Adapter, InboundMessage
from lunamoth.protocol import MUSE, SAY, TextDelta, ThinkDelta, ToolEnd, ToolStart
from lunamoth.server.dispatch import JsonRpcDispatcher
from lunamoth.server.messaging_host import MessagingHost


class _Adapter(Adapter):
    max_message_length = 0

    def __init__(self, name="weixin"):
        self._name = name
        self.sent: list[str] = []

    @property
    def name(self):
        return self._name

    def run(self, inbox):
        return None

    def send(self, text: str):
        self.sent.append(text)


class _Handle:
    def __init__(self):
        self.attached = False
        self.user_calls: list[str] = []

    def set_permission_hook(self, hook):
        pass

    def attach(self, present=True):
        self.attached = True
        return {"opening": "adopt"}

    def detach(self):
        self.attached = False

    def stream_user(self, text):
        self.user_calls.append(text)
        yield ThinkDelta("private")
        yield TextDelta("musing ", MUSE)
        yield ToolStart("terminal")
        yield TextDelta("hi there", SAY)
        yield ToolEnd("terminal", summary="x")


def _host_with_adapter(handle, adapter, frames):
    dispatch = JsonRpcDispatcher(frames.append, handle=handle)
    host = MessagingHost(dispatch, "/tmp/does-not-matter.json")
    dispatch.set_messaging_host(host)
    # Drive the relay path directly (no real adapter I/O / config file).
    host._allowed = {"u1"}
    return dispatch, host


def test_wechat_turn_shares_agent_say_to_adapter_events_to_transport():
    handle = _Handle()
    adapter = _Adapter()
    frames: list[dict] = []
    dispatch, host = _host_with_adapter(handle, adapter, frames)

    host._process(adapter, InboundMessage("u1", "Alice", "hi"))

    # (a) the turn ran on the shared handle
    assert handle.user_calls == ["hi"]
    # (c) only say-channel text went back to WeChat
    assert adapter.sent == ["hi there"]
    # (b) the turn's events streamed onto the transport (the app sees it live),
    # including muse/tool events the adapter intentionally never receives.
    channels = [
        f["params"].get("channel")
        for f in frames
        if f.get("method") == "event" and f["params"].get("type") == "text"
    ]
    assert SAY in channels and MUSE in channels
    kinds = [f["params"].get("type") for f in frames if f.get("method") == "event"]
    assert "tool_start" in kinds and "think" in kinds


def test_wechat_unauthorized_sender_refused_not_run():
    handle = _Handle()
    adapter = _Adapter()
    frames: list[dict] = []
    dispatch, host = _host_with_adapter(handle, adapter, frames)

    host._process(adapter, InboundMessage("stranger", "Mallory", "hi"))
    assert handle.user_calls == []          # no turn on the shared agent
    assert len(adapter.sent) == 1           # one refusal
    assert "hi there" not in adapter.sent


def test_wechat_redelivery_deduped():
    handle = _Handle()
    adapter = _Adapter()
    frames: list[dict] = []
    dispatch, host = _host_with_adapter(handle, adapter, frames)

    msg = InboundMessage("u1", "Alice", "hi", message_id="MSG-7")
    host._process(adapter, msg)
    host._process(adapter, msg)  # platform redelivery
    assert handle.user_calls == ["hi"]      # only one turn
