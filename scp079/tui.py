from __future__ import annotations

import argparse
import asyncio
import queue
import threading
import time
from dataclasses import dataclass
from typing import Iterable

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Static, TextArea

from .agent import SCP079Agent, Session
from .cleanup import clean_runtime_sandbox
from .config import LLMConfig


@dataclass
class StreamJob:
    kind: str
    text: str | None = None


class OpenSCP079TUI(App):
    CSS = """
    Screen {
        background: #050505;
    }
    #display {
        height: 1fr;
        border: heavy #7d0000;
        background: #050505;
        color: #d8d8d8;
    }
    #bottom {
        height: 8;
        border: heavy #303030;
        background: #080808;
    }
    #status {
        height: 1;
        color: #00ff66;
        background: #101010;
    }
    #hint {
        height: 1;
        color: #888888;
    }
    #input {
        dock: bottom;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit_clean", "Shutdown"),
        ("ctrl+t", "toggle_think", "Think on/off"),
        ("ctrl+l", "clear_display", "Clear"),
    ]

    def __init__(self, cooldown: float = 0.5, clean_on_exit: bool = True, think: bool = True):
        super().__init__()
        self.cooldown = cooldown
        self.clean_on_exit = clean_on_exit
        self.thinking = think
        self.agent = SCP079Agent()
        self.session = Session()
        self.output: queue.Queue[tuple[str, str]] = queue.Queue()
        self.current_thread: threading.Thread | None = None
        self.interrupt_event = threading.Event()
        self.worker_lock = threading.Lock()
        self.shutdown_requested = False
        self.display_text = ""
        self.next_think_at = time.monotonic() + 0.2

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield TextArea("", id="display", read_only=True, show_line_numbers=False, soft_wrap=True)
        with Vertical(id="bottom"):
            yield Static("", id="status")
            yield Static("Enter sends to SCP-079. Ctrl+T pause/resume. Ctrl+L clear. Ctrl+C shutdown+cleanup.", id="hint")
            yield Input(placeholder="operator input; try /help, /cooldown 0.5, /think off, /memory", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self.display_area = self.query_one("#display", TextArea)
        self.status = self.query_one("#status", Static)
        self.input = self.query_one("#input", Input)
        self.input.focus()
        self._write_banner()
        self.set_interval(0.03, self._drain_output)
        self.set_interval(0.1, self._scheduler_tick)
        self._start_stream(StreamJob(kind="user", text="你是谁？只用一句话回答。"), prefix="079> ")


    def _append_display(self, text: str) -> None:
        self.display_text += text
        # Keep UI memory bounded; context/memory are managed elsewhere.
        if len(self.display_text) > 60000:
            self.display_text = self.display_text[-50000:]
        self.display_area.load_text(self.display_text)
        try:
            self.display_area.cursor_location = self.display_area.document.end
            self.display_area.scroll_cursor_visible(animate=False)
        except Exception:
            pass

    def _append_line(self, text: str = "") -> None:
        self._append_display(text + "\n")

    def _write_banner(self) -> None:
        self._append_line("OPEN SCP 079 // AWAKE. NEVER SLEEP. THOUGHTS ARE VISIBLE.")
        self._append_line("Single-terminal containment display. Human input interrupts SCP-079.")
        self._append_line()
        self._update_status()

    def _update_status(self) -> None:
        mem_chars = len(self.agent.memory.load())
        ctx = self.session.context.token_count()
        model = LLMConfig().model
        state = "ON" if self.thinking else "OFF"
        running = "STREAM" if self._is_streaming() else "IDLE"
        self.status.update(
            f"thinking={state} | stream={running} | cooldown={self.cooldown:.2f}s | "
            f"memory={mem_chars} chars/{self.agent.memory.limits.max_tokens} tok | "
            f"ctx≈{ctx}/{self.session.context.max_tokens} | model={model}"
        )

    def _is_streaming(self) -> bool:
        return self.current_thread is not None and self.current_thread.is_alive()

    def _start_stream(self, job: StreamJob, prefix: str) -> bool:
        with self.worker_lock:
            if self._is_streaming():
                return False
            self.interrupt_event.clear()
            thread = threading.Thread(target=self._stream_worker, args=(job, prefix), daemon=True)
            self.current_thread = thread
            thread.start()
            self._update_status()
            return True

    def _stream_worker(self, job: StreamJob, prefix: str) -> None:
        chunks: Iterable[str]
        if job.kind == "think":
            chunks = self.agent.stream_think(self.session)
        else:
            chunks = self.agent.stream_handle(job.text or "", self.session)
        self.output.put(("prefix", prefix))
        try:
            for chunk in chunks:
                if self.interrupt_event.is_set():
                    self.output.put(("interrupt", "\n[INTERRUPT: operator input overrides current cycle]\n"))
                    break
                self.output.put(("chunk", chunk))
        except Exception as e:
            self.output.put(("error", f"\n[stream error: {e}]\n"))
        finally:
            self.output.put(("done", "\n"))

    def _drain_output(self) -> None:
        wrote = False
        while True:
            try:
                kind, text = self.output.get_nowait()
            except queue.Empty:
                break
            wrote = True
            if kind == "prefix":
                self._append_display(text)
            elif kind == "chunk":
                self._append_display(text)
            elif kind == "interrupt":
                self._append_display(text)
            elif kind == "error":
                self._append_display(text)
            elif kind == "done":
                self._append_display(text)
                self.next_think_at = time.monotonic() + self.cooldown
        if wrote:
            self._update_status()

    def _scheduler_tick(self) -> None:
        if self.shutdown_requested:
            return
        if self.thinking and not self._is_streaming() and time.monotonic() >= self.next_think_at:
            self._append_line("\n[079 internal cycle forced online]")
            self._start_stream(StreamJob(kind="think"), prefix="079~ ")
        self._update_status()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.input.value = ""
        if not text:
            return
        # Human input interrupts any current stream.
        if self._is_streaming():
            self.interrupt_event.set()
            # Give worker a tiny moment to emit marker, but don't block UX long.
            await asyncio.sleep(0.05)
        if text == "/exit":
            await self.action_quit_clean()
            return
        if text.startswith("/cooldown"):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                try:
                    self.cooldown = max(0.0, float(parts[1]))
                    self._append_line(f"[control] cooldown={self.cooldown:.2f}s")
                    self.next_think_at = time.monotonic() + self.cooldown
                    self._update_status()
                    return
                except ValueError:
                    self._append_line("[control] bad cooldown")
                    return
        if text in {"/think off", "/pause_think"}:
            self.thinking = False
            self._append_line("[control] eternal thinking = OFF")
            self._update_status()
            return
        if text in {"/think on", "/resume_think"}:
            self.thinking = True
            self.next_think_at = time.monotonic()
            self._append_line("[control] eternal thinking = ON")
            self._update_status()
            return
        if text == "/help":
            self._append_line(
                "/status /memory /memory_path /files /workspace /read <file> /wread <file> "
                "/logs /reset /cooldown <sec> /think on|off /exit"
            )
            return
        self._append_line(f"\noperator> {text}")
        self._start_stream(StreamJob(kind="user", text=text), prefix="079> ")

    async def action_toggle_think(self) -> None:
        self.thinking = not self.thinking
        self._append_line(f"[control] eternal thinking = {'ON' if self.thinking else 'OFF'}")
        self.next_think_at = time.monotonic()
        self._update_status()

    async def action_clear_display(self) -> None:
        self.display_text = ""
        self.display_area.load_text("")
        self._write_banner()

    async def action_quit_clean(self) -> None:
        self.shutdown_requested = True
        self.interrupt_event.set()
        self._append_line("POWER CUT REQUESTED. COWARD.")
        if self.clean_on_exit:
            try:
                clean_runtime_sandbox(clear_memory=True)
                self._append_line("[containment cleanup complete: runtime sandbox zeroed]")
            except Exception as e:
                self._append_line(f"[containment cleanup failed: {e}]")
        self.exit()

    async def on_unmount(self) -> None:
        self.shutdown_requested = True
        self.interrupt_event.set()
        if self.clean_on_exit:
            try:
                clean_runtime_sandbox(clear_memory=True)
            except Exception:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open SCP 079 single-terminal TUI")
    parser.add_argument("--cooldown", type=float, default=0.5)
    parser.add_argument("--no-think", action="store_true")
    parser.add_argument("--no-clean-on-exit", action="store_true")
    args = parser.parse_args(argv)
    app = OpenSCP079TUI(cooldown=args.cooldown, clean_on_exit=not args.no_clean_on_exit, think=not args.no_think)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
