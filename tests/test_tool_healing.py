"""Tests for self-healing tool calls (text → structured promotion)."""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms.base import LLMResponse
from shipit_agent.tool_healing import heal_tool_calls

ALLOWED = {"web_search", "read_file"}


class TestFormats:
    def test_tagged_format(self) -> None:
        text = ('Let me search.\n<tool_call>{"name": "web_search", '
                '"arguments": {"query": "gemma 4"}}</tool_call>')
        cleaned, calls = heal_tool_calls(text, ALLOWED)
        assert len(calls) == 1
        assert calls[0].name == "web_search"
        assert calls[0].arguments == {"query": "gemma 4"}
        assert cleaned == "Let me search."          # span removed exactly

    def test_fenced_json(self) -> None:
        text = ('```json\n{"name": "read_file", "arguments": '
                '{"path": "app.py"}}\n```')
        _, calls = heal_tool_calls(text, ALLOWED)
        assert calls[0].name == "read_file"

    def test_bare_json_object(self) -> None:
        text = '{"name": "web_search", "arguments": {"query": "x"}}'
        cleaned, calls = heal_tool_calls(text, ALLOWED)
        assert calls and cleaned == ""

    def test_nested_function_shape(self) -> None:
        text = ('<tool_call>{"function": {"name": "web_search", '
                '"arguments": "{\\"query\\": \\"y\\"}"}}</tool_call>')
        _, calls = heal_tool_calls(text, ALLOWED)
        assert calls[0].arguments == {"query": "y"}


class TestInvariants:
    def test_undeclared_tool_left_as_text(self) -> None:
        text = '<tool_call>{"name": "rm_rf", "arguments": {}}</tool_call>'
        cleaned, calls = heal_tool_calls(text, ALLOWED)
        assert calls == []
        assert cleaned == text                       # byte-identical

    def test_unparseable_left_as_text(self) -> None:
        text = "<tool_call>{not json}</tool_call> plus prose"
        cleaned, calls = heal_tool_calls(text, ALLOWED)
        assert calls == [] and cleaned == text

    def test_surrounding_prose_preserved(self) -> None:
        text = ('Before.\n<tool_call>{"name": "web_search", "arguments": {}}'
                "</tool_call>\nAfter stays.")
        cleaned, calls = heal_tool_calls(text, ALLOWED)
        assert calls and "Before." in cleaned and "After stays." in cleaned

    def test_plain_answer_untouched(self) -> None:
        text = "The answer is 42. Here is JSON: {\"a\": 1}."
        cleaned, calls = heal_tool_calls(text, ALLOWED)
        assert calls == [] and cleaned == text

    def test_empty_allowlist_never_heals(self) -> None:
        text = '<tool_call>{"name": "web_search", "arguments": {}}</tool_call>'
        assert heal_tool_calls(text, set()) == (text, [])


class TestRuntimeIntegration:
    class TextCallLLM:
        """Emits the call as TEXT on turn 1 — like a small open-weight model."""

        def __init__(self) -> None:
            self.turn = 0

        def complete(self, *, messages, tools=None, **_kw) -> LLMResponse:
            self.turn += 1
            if self.turn == 1:
                return LLMResponse(content=(
                    'I will add the numbers.\n<tool_call>{"name": "add", '
                    '"arguments": {"a": 2, "b": 3}}</tool_call>'))
            return LLMResponse(content="The sum is 5.")

    @staticmethod
    def _add(a: int, b: int, **_ignored: Any) -> str:
        return str(a + b)

    def test_text_call_is_healed_and_executed(self) -> None:
        agent = Agent(
            llm=self.TextCallLLM(),
            tools=[FunctionTool.from_callable(self._add, name="add")],
            auto_use_skills=False,
        )
        result = agent.run("2+3?")
        assert result.output == "The sum is 5."
        assert any(e.type == "tool_call_healed" for e in result.events)
        assert any(e.type == "tool_completed" and e.payload["tool"] == "add"
                   for e in result.events)

    def test_healing_can_be_disabled(self) -> None:
        agent = Agent(
            llm=self.TextCallLLM(),
            tools=[FunctionTool.from_callable(self._add, name="add")],
            auto_use_skills=False,
            heal_tool_calls=False,
        )
        result = agent.run("2+3?")
        assert not any(e.type == "tool_call_healed" for e in result.events)
        assert "<tool_call>" in result.output       # left as text, run ended


class TestNudgeOnStall:
    class StallingLLM:
        """Turn 1: narrates intent, no call. Turn 2 (post-nudge): calls."""

        def __init__(self) -> None:
            self.turn = 0
            self.saw_nudge = False

        def complete(self, *, messages, tools=None, **_kw) -> LLMResponse:
            self.turn += 1
            texts = [
                (m.get("content") if isinstance(m, dict) else m.content) or ""
                for m in messages
            ]
            if any("did not call any tool" in t for t in texts):
                self.saw_nudge = True
            if self.turn == 1:
                return LLMResponse(content="Let me use the add tool for this.")
            if self.turn == 2:
                from shipit_agent.llms.base import ToolCall

                return LLMResponse(tool_calls=[
                    ToolCall(name="add", arguments={"a": 2, "b": 3})])
            return LLMResponse(content="The sum is 5.")

    @staticmethod
    def _add(a: int, b: int, **_ignored) -> str:
        return str(a + b)

    def test_stall_is_nudged_then_recovers(self) -> None:
        llm = self.StallingLLM()
        agent = Agent(
            llm=llm,
            tools=[FunctionTool.from_callable(self._add, name="add")],
            auto_use_skills=False,
            max_iterations=6,
        )
        result = agent.run("2+3?")
        assert llm.saw_nudge                        # nudge message reached the LLM
        assert result.output == "The sum is 5."
        assert any(e.payload.get("nudge") for e in result.events
                   if e.type == "tool_call_healed")

    def test_normal_short_answer_not_nudged(self) -> None:
        class Direct:
            def complete(self, **_kw):
                return LLMResponse(content="4")

        agent = Agent(llm=Direct(),
                      tools=[FunctionTool.from_callable(self._add, name="add")],
                      auto_use_skills=False)
        result = agent.run("2+2?")
        assert result.output == "4"
        assert not any(e.payload.get("nudge") for e in result.events
                       if e.type == "tool_call_healed")

    def test_nudge_capped_at_one(self) -> None:
        class AlwaysStalls:
            def complete(self, **_kw):
                return LLMResponse(content="Let me use the add tool now.")

        agent = Agent(llm=AlwaysStalls(),
                      tools=[FunctionTool.from_callable(self._add, name="add")],
                      auto_use_skills=False, max_iterations=6)
        result = agent.run("2+3?")
        nudges = [e for e in result.events
                  if e.type == "tool_call_healed" and e.payload.get("nudge")]
        assert len(nudges) == 1                     # capped, no dead loop


class TestChunkOverlapBudget:
    """Unsloth-style carry_budget: overlap never overflows the chunk target."""

    def test_overlap_capped_by_remaining_room(self) -> None:
        from shipit_agent.rag import Document as RAGDocument
        from shipit_agent.rag.chunker import DocumentChunker

        # Sentences sized so every chunk lands near the target — a full
        # overlap prepend would blow past target_chars without the budget.
        text = " ".join(("word " * 60).strip() + "." for _ in range(12))
        chunker = DocumentChunker(target_tokens=80, overlap_tokens=64)
        chunks = chunker.chunk(RAGDocument(id="d1", content=text))
        assert len(chunks) > 2
        target_chars = 80 * 4
        for chunk in chunks:
            # small tolerance for the title/metadata suffix machinery
            assert len(chunk.text) <= target_chars * 1.3, len(chunk.text)

    def test_small_chunks_still_get_overlap(self) -> None:
        from shipit_agent.rag import Document as RAGDocument
        from shipit_agent.rag.chunker import DocumentChunker

        text = "First sentence here. " * 20 + "MARKER unique tail. " + "Second block. " * 20
        chunker = DocumentChunker(target_tokens=60, overlap_tokens=20)
        chunks = chunker.chunk(RAGDocument(id="d2", content=text))
        joined = [c.text for c in chunks]
        # at least one later chunk carries text from its predecessor
        assert any(i > 0 and joined[i - 1][-30:].split()[-1] in joined[i]
                   for i in range(1, len(joined)))
