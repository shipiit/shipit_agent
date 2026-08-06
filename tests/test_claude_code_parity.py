"""Tests for the Claude-Code-parity round: cancellation, edit hardening,
LLM compaction, rich rendering, and the CLI permission prompt."""

from __future__ import annotations

import io
import os
import time

from shipit_agent import Agent, FunctionTool, StreamRenderer
from shipit_agent.llms.base import LLMResponse, ToolCall
from shipit_agent.models import AgentEvent, Message
from shipit_agent.runtime import AgentRuntime, RuntimeState
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.edit_file import EditFileTool
from shipit_agent.tools.file_read import FileReadTool


def _add(a: int, b: int, **_ignored) -> str:
    return str(a + b)


class LoopingLLM:
    """Calls a tool forever — used to prove cancellation stops the loop."""

    def complete(self, *, messages, tools=None, **_kw) -> LLMResponse:
        return LLMResponse(
            tool_calls=[ToolCall(name="add", arguments={"a": 1, "b": 1})]
        )


class TestCancellation:
    def test_cancel_mid_run_stops_the_loop(self) -> None:
        agent = Agent(
            llm=LoopingLLM(),
            tools=[],  # filled below so the tool can reach the agent
            auto_use_skills=False,
            max_iterations=50,
        )

        def cancelling_add(a: int, b: int, **_ignored) -> str:
            agent.cancel()  # a user pressing ESC mid-tool
            return str(a + b)

        agent.tools.append(FunctionTool.from_callable(cancelling_add, name="add"))
        result = agent.run("loop forever")
        events_seen = [e.type for e in result.events]
        assert "run_cancelled" in events_seen
        # stopped right after the first iteration, far under the 50 budget
        assert events_seen.count("step_started") <= 2
        assert result.events[-1].payload.get("cancelled") is True

    def test_cancel_is_noop_when_idle(self) -> None:
        agent = Agent(llm=LoopingLLM(), auto_use_skills=False)
        agent.cancel()  # must not raise


class TestEditHardening:
    def _tools(self, tmp_path):
        return (
            FileReadTool(root_dir=str(tmp_path)),
            EditFileTool(root_dir=str(tmp_path)),
            ToolContext(prompt="", system_prompt="", state={}),
        )

    def test_edit_blocked_without_read(self, tmp_path) -> None:
        (tmp_path / "a.txt").write_text("hello world")
        _, edit, ctx = self._tools(tmp_path)
        out = edit.run(ctx, path="a.txt", old_text="hello", new_text="hi")
        assert "read the file first" in out.text

    def test_external_change_detected(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("hello world")
        read, edit, ctx = self._tools(tmp_path)
        read.run(ctx, path="a.txt")
        # simulate an external writer touching the file after the read
        f.write_text("hello world!!")
        os.utime(f, ns=(time.time_ns(), time.time_ns() + 1_000_000))
        out = edit.run(ctx, path="a.txt", old_text="hello", new_text="hi")
        assert "changed on disk" in out.text
        assert out.metadata["error"] == "stale_read"

    def test_successful_edit_returns_diff(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("hello world\nsecond line\n")
        read, edit, ctx = self._tools(tmp_path)
        read.run(ctx, path="a.txt")
        out = edit.run(ctx, path="a.txt", old_text="hello", new_text="goodbye")
        assert "File patched" in out.text
        assert "-hello world" in out.metadata["diff"]
        assert "+goodbye world" in out.metadata["diff"]
        assert f.read_text().startswith("goodbye world")

    def test_sequential_edits_do_not_trip_guard(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("one two three")
        read, edit, ctx = self._tools(tmp_path)
        read.run(ctx, path="a.txt")
        first = edit.run(ctx, path="a.txt", old_text="one", new_text="1")
        second = edit.run(ctx, path="a.txt", old_text="two", new_text="2")
        assert "File patched" in first.text
        assert "File patched" in second.text
        assert f.read_text() == "1 2 three"


class TestLLMCompaction:
    def test_llm_writes_the_summary(self) -> None:
        class SummarizerLLM:
            def __init__(self):
                self.summarize_calls = 0

            def complete(self, *, messages, tools=None, metadata=None, **_kw):
                if metadata and metadata.get("purpose") == "context_compaction":
                    self.summarize_calls += 1
                    return LLMResponse(content="DENSE-SUMMARY")
                return LLMResponse(content="done")

        llm = SummarizerLLM()
        runtime = AgentRuntime(llm=llm, prompt="p", context_window_tokens=100)
        messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="x" * 300),
            Message(role="assistant", content="a" * 300),
            Message(role="tool", name="t", content="y" * 300),
            Message(role="user", content="q2"),
            Message(role="assistant", content="b" * 300),
            Message(role="tool", name="t", content="z" * 300),
            Message(role="user", content="latest"),
        ]
        _before = messages
        compacted = runtime.compact(RuntimeState(), _before, 1)
        did = compacted is not _before
        assert did
        assert llm.summarize_calls == 1
        summary = next(m for m in compacted if m.metadata.get("compacted"))
        assert "DENSE-SUMMARY" in summary.content

    def test_falls_back_when_llm_fails(self) -> None:
        class BrokenLLM:
            def complete(self, **_kw):
                raise RuntimeError("no summarizer today")

        runtime = AgentRuntime(llm=BrokenLLM(), prompt="p", context_window_tokens=100)
        messages = [
            Message(role="user", content="important-fact " + "x" * 300),
            Message(role="assistant", content="a" * 300),
            Message(role="tool", name="t", content="y" * 300),
            Message(role="user", content="q"),
            Message(role="assistant", content="b" * 300),
            Message(role="tool", name="t", content="z" * 300),
            Message(role="user", content="latest"),
        ]
        _before = messages
        compacted = runtime.compact(RuntimeState(), _before, 1)
        did = compacted is not _before
        assert did
        summary = next(m for m in compacted if m.metadata.get("compacted"))
        assert "important-fact" in summary.content  # mechanical fallback kept it


class TestRichRendering:
    def _events(self):
        return [
            AgentEvent(type="tool_called", message="",
                       payload={"tool": "bash", "call_id": "c1",
                                "arguments": {"command": "ls"}}),
            AgentEvent(type="tool_completed", message="",
                       payload={"tool": "bash", "call_id": "c1",
                                "output": "a.txt", "duration_ms": 12.0}),
            AgentEvent(type="run_completed", message="",
                       payload={"output": "done"}),
        ]

    def test_rich_style_uses_claude_cards_and_ansi(self) -> None:
        buf = io.StringIO()
        r = StreamRenderer(file=buf, style="rich")
        for e in self._events():
            r.feed(e)
        r.close()
        text = buf.getvalue()
        assert "⏺ " in text and "⎿" in text
        assert "\033[" in text            # ANSI colors present
        assert "bash" in text and "a.txt" in text

    def test_plain_style_has_no_ansi(self) -> None:
        buf = io.StringIO()
        r = StreamRenderer(file=buf, style="plain")
        for e in self._events():
            r.feed(e)
        r.close()
        text = buf.getvalue()
        assert "\033[" not in text
        assert "⚙ bash" in text

    def test_auto_style_plain_for_non_tty(self) -> None:
        buf = io.StringIO()  # not a tty
        r = StreamRenderer(file=buf, style="auto")
        r.feed(self._events()[0])
        assert "\033[" not in buf.getvalue()


class TestCLIPermissionPrompt:
    def _repl(self, answers):
        from shipit_agent.chat_cli import ChatREPL

        class L:
            def complete(self, **_kw):
                return LLMResponse(content="hi")

        repl = ChatREPL(llm=L(), agent_type="agent", use_builtins=False, quiet=True)
        it = iter(answers)
        # patch input used inside the prompt
        import builtins

        self._orig_input = builtins.input
        builtins.input = lambda *_a: next(it)
        return repl

    def teardown_method(self) -> None:
        import builtins

        if hasattr(self, "_orig_input"):
            builtins.input = self._orig_input

    def test_yes_allows_once(self) -> None:
        repl = self._repl(["y", "n"])
        first = repl._permission_prompt("bash", {"command": "ls"})
        second = repl._permission_prompt("bash", {"command": "rm x"})
        assert first.allowed
        assert not second.allowed

    def test_always_persists_for_session(self) -> None:
        repl = self._repl(["a"])
        first = repl._permission_prompt("bash", {"command": "ls"})
        # no more input available — must not prompt again
        second = repl._permission_prompt("bash", {"command": "ls -la"})
        assert first.allowed and second.allowed
        assert "bash" in repl.always_allowed
