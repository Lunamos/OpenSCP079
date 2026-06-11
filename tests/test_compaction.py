from lunamoth.core import compaction
from lunamoth.core.context import ContextBuffer


class FakeLLM:
    def __init__(self, live=True, summary="OLD SUMMARY"):
        self._live, self._summary, self.calls = live, summary, 0

    def is_live(self):
        return self._live

    def raw_complete(self, messages, max_tokens=1024, timeout=60.0):
        self.calls += 1
        return self._summary



def _sc(ctx, window, llm):
    ctx.max_tokens, ctx.trim_buffer_tokens = window, 0
    return compaction.should_compact(ctx, llm)


def _cp(ctx, window, llm):
    ctx.max_tokens, ctx.trim_buffer_tokens = window, 0
    return compaction.compact(ctx, "en", llm)


def _fill(ctx, n, chars=500):
    for i in range(n):
        ctx.add("user" if i % 2 == 0 else "assistant", "x" * chars)


def test_should_compact_threshold():
    ctx = ContextBuffer(max_tokens=10_000_000)
    _fill(ctx, 20, 500)  # ~2540 tokens
    assert _sc(ctx, 1000, FakeLLM())          # 2540 >= 750
    assert not _sc(ctx, 1_000_000, FakeLLM())  # well under 75%
    assert not _sc(ctx, 1000, FakeLLM(live=False))  # offline


def test_compact_replaces_head_keeps_tail():
    ctx = ContextBuffer(max_tokens=10_000_000)  # disable trim so we test compaction alone
    llm = FakeLLM(summary="OLD SUMMARY TEXT")
    _fill(ctx, 40, 500)
    n_before = len(ctx.messages)
    assert _cp(ctx, 4000, llm) is True
    assert llm.calls == 1
    assert ctx.messages[0]["kind"] == "summary"
    assert "OLD SUMMARY TEXT" in ctx.messages[0]["content"]
    assert len(ctx.messages) < n_before                  # head collapsed
    assert ctx.messages[-1]["content"] == "x" * 500      # tail kept verbatim


def test_iterative_summary_folds_previous():
    # A summary message (kind='summary') sits at messages[0] after compaction; the
    # next compaction includes it in the head, so _serialize labels it as the prior
    # summary and the model folds it into the new one — iterative update for free.
    head = [
        {"role": "system", "content": "older facts here", "kind": "summary"},
        {"role": "user", "content": "do the thing"},
        {"role": "assistant", "content": "done"},
    ]
    serialized = compaction._serialize(head)
    assert "earlier summary" in serialized and "older facts here" in serialized


def test_serialize_prunes_tool_outputs_without_mutating_head():
    head = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "terminal", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "line\n" * 200},
    ]
    serialized = compaction._serialize(head)
    assert "terminal output pruned" in serialized
    assert len(serialized) < len(head[1]["content"])
    assert head[1]["content"] == "line\n" * 200  # pruning is only for the summary prompt copy


def test_offline_and_empty_summary_are_noops():
    ctx = ContextBuffer(max_tokens=10_000_000)
    _fill(ctx, 40, 500)
    n = len(ctx.messages)
    assert _cp(ctx, 4000, FakeLLM(live=False)) is False
    assert _cp(ctx, 4000, FakeLLM(summary='')) is False
    assert len(ctx.messages) == n  # unchanged
