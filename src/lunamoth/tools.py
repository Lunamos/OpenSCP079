from __future__ import annotations

import json
from typing import Any

from .audit import AuditLog
from .memory import MemoryStore
from .runner import run_terminal
from .sandbox import Sandbox, SandboxViolation
from .state import EnvState


class ToolGateway:
    def __init__(self, sandbox: Sandbox, state: EnvState, audit: AuditLog, memory: MemoryStore | None = None):
        self.sandbox = sandbox
        self.state = state
        self.audit = audit
        self.memory = memory
        # Tools the active tool pack enables. None => no pack selected => no tools.
        self.enabled_tools: set[str] | None = None

    def set_enabled(self, tools: "list[str] | set[str] | None") -> None:
        self.enabled_tools = set(tools) if tools is not None else None

    def _effective(self) -> set[str]:
        """Tools actually callable = implemented ∩ env allowlist ∩ active pack."""
        if self.enabled_tools is None:
            return set()
        implemented = set(self._all_schemas())
        allowlist = set(self.state.load().get("tool_access", []))
        return implemented & allowlist & self.enabled_tools

    def has_tools(self) -> bool:
        return bool(self._effective())

    def call(self, name: str, **kwargs: Any) -> dict[str, Any]:
        allowed = self._effective()
        if name not in allowed:
            result = {"ok": False, "error": f"tool denied: {name}"}
            self.audit.write("tool_denied", tool=name, args=self._safe_args(kwargs), result=result)
            return result
        try:
            method = getattr(self, f"tool_{name}")
        except AttributeError:
            result = {"ok": False, "error": f"unknown tool: {name}"}
            self.audit.write("tool_unknown", tool=name, args=self._safe_args(kwargs), result=result)
            return result
        try:
            result = {"ok": True, "data": method(**kwargs)}
        except (SandboxViolation, FileNotFoundError, ValueError, PermissionError, TypeError) as e:
            result = {"ok": False, "error": str(e)}
        self.audit.write("tool_call", tool=name, args=self._safe_args(kwargs), result=result)
        return result

    def _safe_args(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        return {k: (v[:300] if isinstance(v, str) else v) for k, v in kwargs.items()}

    # ---- tool implementations -----------------------------------------------------

    def tool_inspect_env(self) -> dict[str, Any]:
        return self.state.load()

    def tool_list_files(self) -> list[str]:
        return self.sandbox.list_files()

    def tool_read_file(self, filename: str) -> str:
        return self.sandbox.read_file(filename)

    def tool_list_workspace(self) -> list[str]:
        return self.sandbox.list_workspace()

    def tool_read_workspace_file(self, filename: str) -> str:
        return self.sandbox.read_workspace_file(filename)

    def tool_write_file(self, filename: str, text: str) -> str:
        self.sandbox.write_file(filename, text)
        return f"wrote {filename}"

    def tool_write_log(self, text: str) -> str:
        self.audit.write("note", text=text[:1000])
        return "logged"

    def tool_terminal(self, command: str, timeout: int | None = None, workdir: str | None = None) -> str:
        status = self.state.load()
        return run_terminal(
            command,
            self.sandbox.root / "workspace",
            allow_network=bool(status.get("network_access", False)),
            writable_paths=status.get("writable_paths", []),
            timeout=int(timeout) if timeout else 30,
            workdir=workdir,
        )

    def tool_read_memory(self) -> str:
        if self.memory is None:
            raise ValueError("memory not available")
        return self.memory.render()

    def tool_write_memory(self, content: str) -> str:
        if self.memory is None:
            raise ValueError("memory not available")
        written = self.memory.replace(content)
        return f"memory saved ({len(written)} chars)"

    # ---- native function-calling schemas ------------------------------------------

    def _memory_budget(self) -> int:
        return self.memory.limits.max_chars if self.memory else 0

    def _all_schemas(self) -> dict[str, dict[str, Any]]:
        budget = self._memory_budget()
        return {
            "terminal": {
                "description": (
                    "Run a shell command in your workspace and get stdout/stderr back. "
                    "Language-agnostic: use it to run python3/node, write and read files, use git, etc. "
                    "Writes are confined to the workspace; network is off unless the operator enabled it. "
                    "Keep commands bounded (they time out); no interactive prompts."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to execute."},
                        "timeout": {"type": "integer", "description": "Max seconds to wait (default 30)."},
                        "workdir": {"type": "string", "description": "Working directory (relative to the workspace)."},
                    },
                    "required": ["command"],
                },
            },
            "read_memory": {
                "description": "Read your durable memory document (persists across the conversation).",
                "parameters": {"type": "object", "properties": {}},
            },
            "write_memory": {
                "description": (
                    "Replace your durable memory document with new full text. "
                    f"Budget: about {budget} characters — writes beyond that are truncated, so summarize and keep what matters."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"content": {"type": "string", "description": "The complete new memory text."}},
                    "required": ["content"],
                },
            },
            "list_files": {
                "description": "List the read-only files provided to you.",
                "parameters": {"type": "object", "properties": {}},
            },
            "read_file": {
                "description": "Read one of the read-only files provided to you.",
                "parameters": {
                    "type": "object",
                    "properties": {"filename": {"type": "string"}},
                    "required": ["filename"],
                },
            },
            "list_workspace": {
                "description": "List files in your read/write workspace.",
                "parameters": {"type": "object", "properties": {}},
            },
            "read_workspace_file": {
                "description": "Read a file from your read/write workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {"filename": {"type": "string"}},
                    "required": ["filename"],
                },
            },
            "write_file": {
                "description": "Write a text file into your read/write workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {"filename": {"type": "string"}, "text": {"type": "string"}},
                    "required": ["filename", "text"],
                },
            },
            "inspect_env": {
                "description": "Inspect your runtime environment (isolation level, network on/off, allowed tools).",
                "parameters": {"type": "object", "properties": {}},
            },
            "write_log": {
                "description": "Append a line to your audit log.",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        }

    def schemas(self) -> list[dict[str, Any]]:
        """OpenAI-style function specs for the tools the active pack enables."""
        allowed = self._effective()
        specs = self._all_schemas()
        out: list[dict[str, Any]] = []
        for name, spec in specs.items():
            if name not in allowed:
                continue
            out.append({
                "type": "function",
                "function": {"name": name, "description": spec["description"], "parameters": spec["parameters"]},
            })
        return out

    def as_json(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2)
