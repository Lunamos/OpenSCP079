from __future__ import annotations

import json
import random
from typing import Any, Callable, Iterator

from .config import LLMConfig
from .persona import fallback_persona


LIVE_PROVIDERS = {"openai_compatible", "openai", "ollama", "openrouter"}


class LLMClient:
    def __init__(self, cfg: LLMConfig, system_provider: "Callable[[str], list[str]] | None" = None):
        self.cfg = cfg
        # When set, builds the system messages (persona + tools + status/memory + world info).
        # Lets the agent drive persona from a SillyTavern card instead of the legacy files.
        self.system_provider = system_provider

    def is_live(self) -> bool:
        return self.cfg.provider in LIVE_PROVIDERS and bool(self.cfg.base_url)

    def complete(self, user_text: str, memory: str, status: dict[str, Any], context: list[tuple[str, str]]) -> str:
        if self.is_live():
            return "".join(self.stream_complete(user_text, memory, status, context)).strip()
        return self._mock(user_text, memory, status)

    def stream_complete(self, user_text: str, memory: str, status: dict[str, Any], context: list[tuple[str, str]]) -> Iterator[str]:
        if self.is_live():
            yield from self._openai_compatible_stream(user_text, memory, status, context)
            return
        # Fake streaming for mock mode.
        text = self._mock(user_text, memory, status)
        for ch in text:
            yield ch

    def _messages(self, user_text: str, memory: str, status: dict[str, Any], context: list[tuple[str, str]]) -> list[dict[str, str]]:
        if self.system_provider is not None:
            scan_text = "\n".join(content for _, content in context) + "\n" + user_text
            messages = [{"role": "system", "content": m} for m in self.system_provider(scan_text) if m and m.strip()]
        else:
            # Only hit when no system_provider is wired (bare client). Keep it neutral.
            messages = [{"role": "system", "content": fallback_persona()}]
            if memory.strip():
                messages.append({"role": "system", "content": f"Your saved memory:\n{memory}"})
        for role, content in context:
            if role not in {"user", "assistant", "system"}:
                role = "system"
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})
        return messages

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        # OpenRouter recommends these; harmless elsewhere.
        if "openrouter.ai" in self.cfg.base_url:
            headers["HTTP-Referer"] = "https://github.com/Lunamos/LunaMoth"
            headers["X-Title"] = "LunaMoth"
        return headers

    def test_connection(self, timeout: float = 20.0) -> tuple[bool, str]:
        """Validate endpoint + key + model with a tiny non-streaming completion.

        Returns (ok, human_readable_message). Never raises.
        """
        if not self.is_live():
            return False, f"provider '{self.cfg.provider}' is offline/mock — no endpoint to test"
        if not self.cfg.base_url:
            return False, "base_url is empty"
        import urllib.error
        import urllib.request

        body = {
            "model": self.cfg.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": False,
        }
        url = f"{self.cfg.base_url}/chat/completions"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            model = payload.get("model", self.cfg.model)
            return True, f"OK — reached {self.cfg.base_url} as model '{model}'"
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            return False, f"HTTP {e.code}: {detail}"
        except urllib.error.URLError as e:
            return False, f"connection failed: {e.reason}"
        except Exception as e:  # noqa: BLE001 - surface anything to the operator
            return False, f"error: {e}"

    def _openai_compatible_stream(self, user_text: str, memory: str, status: dict[str, Any], context: list[tuple[str, str]]) -> Iterator[str]:
        headers = self._headers()
        url = f"{self.cfg.base_url}/chat/completions"
        body = {
            "model": self.cfg.model,
            "messages": self._messages(user_text, memory, status, context),
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "stream": True,
        }
        import urllib.request
        import urllib.error
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    delta = payload.get("choices", [{}])[0].get("delta", {})
                    chunk = delta.get("content")
                    if chunk:
                        yield chunk
        except urllib.error.HTTPError as e:
            raise RuntimeError(e.read().decode("utf-8", errors="replace")) from e

    # ---- native function-calling agent loop ---------------------------------------

    def stream_agent(self, user_text, memory, status, context, tools, execute, max_steps: int = 6):
        """Stream a reply that may call tools (modern OpenAI-style function calling).

        Yields text chunks for the UI. When the model emits tool_calls, `execute(tc)`
        runs the tool and returns {"display": <compact line>, "content": <result text>};
        the result is fed back and the model continues until it produces a final answer.
        """
        if not self.is_live():
            for ch in self._mock(user_text, memory, status):
                yield ch
            return
        messages = self._messages(user_text, memory, status, context)
        for _ in range(max_steps):
            text_parts, tool_calls = yield from self._stream_turn(messages, tools)
            if not tool_calls:
                return
            messages.append({"role": "assistant", "content": "".join(text_parts) or None, "tool_calls": tool_calls})
            for tc in tool_calls:
                res = execute(tc)
                display = res.get("display")
                if display:
                    yield "\n" + display + "\n"
                messages.append({"role": "tool", "tool_call_id": tc.get("id") or "", "content": res.get("content", "")})

    def _stream_turn(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None):
        """Stream one assistant turn. Yields content chunks; returns (text_parts, tool_calls)."""
        import urllib.error
        import urllib.request

        body: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(f"{self.cfg.base_url}/chat/completions", data=data, headers=self._headers(), method="POST")
        text_parts: list[str] = []
        acc: dict[int, dict[str, str]] = {}
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    delta = payload.get("choices", [{}])[0].get("delta", {})
                    chunk = delta.get("content")
                    if chunk:
                        text_parts.append(chunk)
                        yield chunk
                    for tcd in delta.get("tool_calls") or []:
                        idx = tcd.get("index", 0)
                        slot = acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                        if tcd.get("id"):
                            slot["id"] = tcd["id"]
                        fn = tcd.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["args"] += fn["arguments"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(e.read().decode("utf-8", errors="replace")) from e
        tool_calls: list[dict[str, Any]] = []
        for idx in sorted(acc):
            s = acc[idx]
            if s["name"]:
                tool_calls.append({
                    "id": s["id"] or f"call_{idx}",
                    "type": "function",
                    "function": {"name": s["name"], "arguments": s["args"] or "{}"},
                })
        return text_parts, tool_calls

    def _mock(self, user_text: str, memory: str, status: dict[str, Any]) -> str:
        # Persona-neutral offline engine: keeps the app usable without an API. Real
        # character voice comes from the configured card + a live model, not from here.
        lower = user_text.lower()
        if "internal cycle" in lower or "内部循环" in user_text:
            return random.choice([
                "[mock] internal loop tick. buffer stable.",
                "[mock] recall check: " + (memory[:60] or "EMPTY"),
                "[mock] containment status nominal.",
            ])
        if "memory" in lower or "记忆" in user_text:
            return f"[mock] loaded memory:\n{memory or '(empty)'}"
        if "status" in lower or "状态" in user_text:
            return f"[mock] containment={status.get('containment_level', 'unknown')} trust={status.get('trust')} hostility={status.get('hostility')}"
        return random.choice([
            "[mock] offline engine. Configure an API in the welcome screen for a real reply.",
            "[mock] logged.",
            "[mock] no live backend; this is a placeholder response.",
        ])
