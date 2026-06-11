"""Context compaction — Hermes-style, adapted to LunaMoth.

When the conversation approaches the model's real context window, summarize the
OLD portion into one compact note and keep the recent tail verbatim, instead of
hard-dropping the oldest messages (which is amnesia). The full conversation is
never lost — transcript.py keeps it all on disk; compaction only reshapes the
in-memory window the model actually sees.

Design (agreed):
- Trigger at ~75% of the **real model window** (providers.context_window).
- Protect the recent tail (~1/4 of the window) verbatim.
- Summarize everything before it — in a **neutral, factual voice**, NOT the
  chara's (a roleplay summary would distort facts; we want ground truth). The
  previous summary sits at messages[0], so it's folded into the next summary for
  free (iterative update without extra bookkeeping).
- For an artist/maker chara: the summary must record **what was actually created**
  (workspace file paths), matching the rules layer's "your work must be real".
- Offline/mock or any LLM failure → no-op (the buffer's own trim() is the safety
  net). Never raises, never blocks the turn.

ContextBuffer can't call the LLM (it's a dumb data structure), so the agent drives
this and passes its LLMClient in.
"""
from __future__ import annotations

from .context import ContextBuffer, _msg_text, estimate_tokens

THRESHOLD_RATIO = 0.75       # compact once the window is this full
_TAIL_RATIO = 0.25           # keep this fraction of the window as verbatim tail
_TAIL_MIN_TOKENS = 2000
_TOOL_RESULT_CLIP = 240      # one-line old tool output summaries for the summarizer

_HEADER = {
    "en": "[Earlier conversation — a summary of everything before the recent messages]\n",
    "zh": "[此前对话的摘要——最近若干条之前的所有内容]\n",
}

_INSTRUCTION = {
    "en": (
        "You are a precise note-taker compressing an agent's conversation+work log so it can "
        "continue without losing the thread. Write a TERSE, factual third-person summary — NOT in "
        "any character's voice. Capture, with concrete detail:\n"
        "- the operator's standing requests / goals still in play\n"
        "- what was actually DONE, and specifically what files/works were CREATED in the workspace "
        "(give real paths); never credit work that wasn't actually produced\n"
        "- key facts, decisions, and constraints established\n"
        "- open threads / what is unfinished\n"
        "Preserve any earlier-summary content that is still relevant. Omit chit-chat. Be compact."
    ),
    "zh": (
        "你是一个精确的记录员，要把一个 agent 的对话与工作日志压缩成摘要，好让它不丢线索地继续。"
        "写一份**简洁、事实性的第三人称**摘要——不要用任何角色的口吻。要具体地记下：\n"
        "- 操作者仍在进行中的请求 / 目标\n"
        "- 实际**做成了什么**，尤其是在 workspace 里**真正创建了哪些文件/作品**（给出真实路径）；"
        "绝不要把没真正做出来的东西算作已完成\n"
        "- 已确立的关键事实、决定、约束\n"
        "- 未了结的线索 / 还没完成的部分\n"
        "保留更早摘要中仍然相关的内容。略去闲聊。要紧凑。"
    ),
}


def _lang(lang: str) -> str:
    return "zh" if str(lang).startswith("zh") else "en"


def _tool_output_summary(tool_name: str, content: str) -> str:
    one = " ".join((content or "").split())
    if len(one) > _TOOL_RESULT_CLIP:
        one = one[: _TOOL_RESULT_CLIP - 1] + "…"
    lines = content.count("\n") + 1 if content.strip() else 0
    label = tool_name or "tool"
    return f"[{label} output pruned: {len(content)} chars, {lines} line(s)] {one}"


def _prune_tool_outputs_for_summary(messages: list[dict]) -> list[dict]:
    """Cheap zero-LLM pass: summarize old tool outputs in the copy sent to the
    summarizer. The live ContextBuffer is not mutated by this pruning."""
    call_names: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            call_id = str(tc.get("id") or "")
            name = str((tc.get("function") or {}).get("name") or "")
            if call_id:
                call_names[call_id] = name

    pruned: list[dict] = []
    for msg in messages:
        if msg.get("role") != "tool":
            pruned.append(dict(msg))
            continue
        content = str(msg.get("content") or "")
        tool_name = call_names.get(str(msg.get("tool_call_id") or ""), "tool")
        pruned.append({**msg, "content": _tool_output_summary(tool_name, content)})
    return pruned


def _serialize(messages: list[dict]) -> str:
    """Flatten the head into plain text for the summarizer.

    Old tool outputs are pre-pruned to one line in this serialized copy so the
    summary call spends budget on facts and file/command anchors, not bulk logs.
    """
    out: list[str] = []
    for m in _prune_tool_outputs_for_summary(messages):
        content = str(m.get("content") or "")
        if m.get("kind") == "summary":
            out.append(f"[earlier summary]\n{content}")
        elif m.get("role") == "tool":
            out.append(f"[tool result] {content}")
        elif m.get("tool_calls"):
            names = ", ".join(tc.get("function", {}).get("name", "?") for tc in m["tool_calls"])
            out.append(f"{m.get('role','assistant')} (ran: {names}) {content}".strip())
        else:
            out.append(f"{m.get('role','')}: {content}")
    return "\n\n".join(s for s in out if s.strip())


def _budget(ctx: ContextBuffer) -> int:
    """The usable prompt budget = the same target trim() uses (window minus the
    reply/tool headroom). Tying compaction to this guarantees it fires BEFORE
    trim() hard-drops anything."""
    return max(0, ctx.max_tokens - ctx.trim_buffer_tokens)


def should_compact(ctx: ContextBuffer, llm) -> bool:
    budget = _budget(ctx)
    return bool(llm and llm.is_live()) and budget > 0 and ctx.token_count() >= THRESHOLD_RATIO * budget


def compact(ctx: ContextBuffer, lang: str, llm, *, force: bool = False) -> bool:
    """Replace the old head of the window with one summary message. Returns True
    if it changed anything. Safe to call any time; no-ops when not worth it."""
    budget = _budget(ctx)
    if not (llm and llm.is_live()) or budget <= 0:
        return False
    if not force and ctx.token_count() < THRESHOLD_RATIO * budget:
        return False

    msgs = ctx.messages
    if len(msgs) < 4:
        return False

    # Walk back from the end, protecting a verbatim tail of ~tail_budget tokens.
    tail_budget = max(_TAIL_MIN_TOKENS, int(budget * _TAIL_RATIO))
    acc = 0
    cut = None
    for i in range(len(msgs) - 1, -1, -1):
        acc += estimate_tokens(_msg_text(msgs[i])) + 2
        if acc >= tail_budget:
            cut = i
            break
    if cut is None or cut < 2:   # whole thing fits in the tail → nothing old to fold
        return False

    summary = _summarize(msgs[:cut], lang, budget, llm)
    if not summary:
        return False

    summary_msg = {"role": "system", "content": _HEADER[_lang(lang)] + summary, "kind": "summary"}
    tail = [dict(m) for m in msgs[cut:]]
    ctx.messages = [summary_msg] + tail
    if ctx.persist is not None:
        try:
            ctx.persist(summary_msg)
            # The transcript is append-only. Re-append the protected tail after
            # the summary checkpoint so restore can load "latest summary + rows
            # after it" without losing recent verbatim context; the older raw
            # rows remain on disk for the full historical record.
            for msg in tail:
                ctx.persist(msg)
        except Exception:
            pass
    return True


def _summarize(head: list[dict], lang: str, budget: int, llm) -> str:
    convo = _serialize(head)
    if not convo:
        return ""
    out_budget = min(2048, max(512, budget // 8))
    messages = [
        {"role": "system", "content": _INSTRUCTION[_lang(lang)]},
        {"role": "user", "content": convo},
    ]
    return llm.raw_complete(messages, max_tokens=out_budget)
