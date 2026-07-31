"""Tests for human-in-the-loop prompts and the bottom-input TUI."""

from __future__ import annotations

import io

from shipit_agent import console_permission_prompt
from shipit_agent.cli.tui import BottomInputTerminal


class TestConsolePermissionPrompt:
    def _prompt(self, answers, always=None):
        it = iter(answers)
        writes: list[str] = []
        cb = console_permission_prompt(
            always_allowed=always, input_fn=lambda: next(it),
            output=writes.append)
        return cb, writes

    def test_yes_no_always(self) -> None:
        always: set[str] = set()
        cb, writes = self._prompt(["y", "n", "a"], always)
        assert cb("bash", {"command": "ls"}).allowed
        assert not cb("bash", {"command": "rm x"}).allowed
        assert cb("bash", {"command": "pwd"}).allowed
        # always persisted — no more input consumed
        assert cb("bash", {"command": "anything"}).allowed
        assert "bash" in always
        assert "⏸ allow bash(" in writes[0]

    def test_eof_denies(self) -> None:
        def boom():
            raise EOFError

        cb = console_permission_prompt(input_fn=boom, output=lambda _t: None)
        assert not cb("bash", {}).allowed

    def test_shared_always_set_across_callbacks(self) -> None:
        shared: set[str] = {"git_ops"}
        cb = console_permission_prompt(always_allowed=shared,
                                       input_fn=lambda: "n",
                                       output=lambda _t: None)
        assert cb("git_ops", {"action": "status"}).allowed  # pre-approved


class TestBottomInputTerminal:
    def test_non_tty_is_plain_passthrough(self, capsys) -> None:
        buf = io.StringIO()  # not a tty
        term = BottomInputTerminal(stream=buf).start()
        assert term.enabled is False
        term.print("hello")
        term.stop()
        assert buf.getvalue() == "hello\n"
        assert "\033[" not in buf.getvalue()

    def test_enabled_uses_scroll_region(self, monkeypatch) -> None:
        import shutil as _shutil

        monkeypatch.setattr(_shutil, "get_terminal_size",
                            lambda fallback=None: type("S", (), {
                                "lines": 24, "columns": 80})())
        buf = io.StringIO()
        term = BottomInputTerminal(stream=buf, enabled=True).start()
        assert term.enabled
        term.print("chat line")
        term.stop()
        out = buf.getvalue()
        assert "\033[1;22r" in out         # scroll region rows 1..height-2
        assert "chat line" in out
        assert "\033[r" in out             # region reset on stop

    def test_read_falls_back_to_input(self, monkeypatch) -> None:
        import builtins

        monkeypatch.setattr(builtins, "input", lambda p="": "typed")
        term = BottomInputTerminal(stream=io.StringIO())  # disabled
        assert term.read("you ▸ ") == "typed"

    def test_tiny_terminal_disables_layout(self, monkeypatch) -> None:
        import shutil as _shutil

        monkeypatch.setattr(_shutil, "get_terminal_size",
                            lambda fallback=None: type("S", (), {
                                "lines": 4, "columns": 80})())
        term = BottomInputTerminal(stream=io.StringIO(), enabled=True).start()
        assert term.enabled is False
