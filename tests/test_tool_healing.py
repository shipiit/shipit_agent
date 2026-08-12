"""Tests for self-healing tool calls (text → structured promotion)."""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms.base import LLMResponse, ToolCall
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

    def test_gemma_relaxed_call_format(self) -> None:
        schemas = {
            "read_file": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            }
        }
        cleaned, calls = heal_tool_calls(
            "I'll inspect it.\n```call:read_file{path:calculator.py}```",
            {"read_file"},
            schemas=schemas,
        )
        assert calls[0].name == "read_file"
        assert calls[0].arguments == {"path": "calculator.py"}
        assert cleaned == "I'll inspect it."

    def test_relaxed_call_still_obeys_declared_schema(self) -> None:
        schemas = {
            "read_file": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            }
        }
        text = "```call:read_file{unknown:calculator.py}```"
        assert heal_tool_calls(text, {"read_file"}, schemas=schemas) == (text, [])

    def test_gemma_at_call_format(self) -> None:
        schemas = {
            "bash": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            }
        }
        cleaned, calls = heal_tool_calls(
            "I will inspect.\n@bash(command='ls -R')",
            {"bash"},
            schemas=schemas,
        )
        assert calls[0].arguments == {"command": "ls -R"}
        assert cleaned == "I will inspect."

    def test_backticked_declared_python_call(self) -> None:
        schemas = {
            "edit_file": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            }
        }
        text = (
            ">Final tool call:\n"
            "`edit_file(path='a.py', old_text='x', new_text='y')`"
        )
        _, calls = heal_tool_calls(text, {"edit_file"}, schemas=schemas)
        assert calls[0].arguments == {
            "path": "a.py",
            "old_text": "x",
            "new_text": "y",
        }

    def test_bare_declared_python_call_from_gemma_rejection(self) -> None:
        schemas = {
            "read_file": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            }
        }
        text = (
            "Unparseable tool-call body from Gemma: "
            'read_file(path="test_calculator.py")\n</code>'
        )
        cleaned, calls = heal_tool_calls(text, {"read_file"}, schemas=schemas)
        assert calls == [
            ToolCall(name="read_file", arguments={"path": "test_calculator.py"})
        ]
        assert cleaned == "Unparseable tool-call body from Gemma: \n</code>"

    def test_bare_call_requires_declared_name_and_schema(self) -> None:
        schemas = {
            "read_file": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            }
        }
        unknown = 'delete_file(path="test_calculator.py")'
        wrong_schema = 'read_file(command="rm -rf .")'
        assert heal_tool_calls(unknown, {"read_file"}, schemas=schemas) == (
            unknown,
            [],
        )
        assert heal_tool_calls(wrong_schema, {"read_file"}, schemas=schemas) == (
            wrong_schema,
            [],
        )

    def test_repeated_identical_bare_call_executes_once(self) -> None:
        schemas = {
            "read_file": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            }
        }
        text = "\n".join(['read_file(path="app.py")'] * 3)
        cleaned, calls = heal_tool_calls(text, {"read_file"}, schemas=schemas)
        assert len(calls) == 1
        assert calls[0].arguments == {"path": "app.py"}
        assert cleaned == ""

    def test_markdown_tool_table_format(self) -> None:
        schemas = {
            "edit_file": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            }
        }
        line = (
            "| `edit_file` | `path='calculator.py'`, "
            "`old_text='return total * count'`, "
            "`new_text='return total / count'` |"
        )
        cleaned, calls = heal_tool_calls(line, {"edit_file"}, schemas=schemas)
        assert cleaned == ""
        assert calls[0].arguments["path"] == "calculator.py"
        assert calls[0].arguments["new_text"] == "return total / count"


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

    def test_multiline_plan_ending_in_next_action_is_nudged(self) -> None:
        class PlanningThenCalling(self.StallingLLM):
            def complete(self, *, messages, tools=None, **kw):
                if self.turn == 0:
                    self.turn += 1
                    return LLMResponse(
                        content=(
                            "I will inspect the project.\n\n"
                            "Plan:\n1. Find files\n2. Read code\n\n"
                            "First, listing the files."
                        )
                    )
                return super().complete(messages=messages, tools=tools, **kw)

        llm = PlanningThenCalling()
        result = Agent(
            llm=llm,
            tools=[FunctionTool.from_callable(self._add, name="add")],
            auto_use_skills=False,
            max_iterations=5,
        ).run("2+3?")

        assert any(e.payload.get("nudge") for e in result.events)

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

    def test_pathological_repetition_is_compacted_and_recovered(self) -> None:
        class RepeatingThenCalling:
            def __init__(self) -> None:
                self.turn = 0
                self.max_assistant_chars = 0

            def complete(self, *, messages, **_kw):
                self.turn += 1
                self.max_assistant_chars = max(
                    [self.max_assistant_chars]
                    + [
                        len(str(getattr(m, "content", "")))
                        for m in messages
                        if getattr(m, "role", None) == "assistant"
                    ]
                )
                if self.turn == 1:
                    repeated = "<thought\n>I will call the add tool.\n" * 500
                    return LLMResponse(content=repeated)
                if self.turn == 2:
                    from shipit_agent.llms.base import ToolCall

                    return LLMResponse(
                        tool_calls=[ToolCall(name="add", arguments={"a": 2, "b": 3})]
                    )
                return LLMResponse(content="The sum is 5.")

        llm = RepeatingThenCalling()
        result = Agent(
            llm=llm,
            tools=[FunctionTool.from_callable(self._add, name="add")],
            auto_use_skills=False,
            max_iterations=5,
        ).run("2+3?")

        assert result.output == "The sum is 5."
        assert llm.max_assistant_chars < 500
        compacted = [e for e in result.events if e.type == "model_output_compacted"]
        assert compacted and compacted[0].payload["removed_lines"] > 900

    def test_pathological_structured_argument_is_compacted_before_execution(self) -> None:
        received: list[str] = []

        def submit(text: str) -> str:
            received.append(text)
            return "accepted"

        class RepeatingArgument:
            def __init__(self) -> None:
                self.turn = 0

            def complete(self, *, messages, **_kwargs):
                self.turn += 1
                if self.turn == 1:
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(
                                name="submit",
                                arguments={
                                    "text": (
                                        "Calling the tool. " * 500
                                        + "{}</markup>" * 500
                                    )
                                },
                            )
                        ]
                    )
                return LLMResponse(content="Submitted.")

        result = Agent(
            llm=RepeatingArgument(),
            tools=[FunctionTool.from_callable(submit, name="submit")],
            auto_use_skills=False,
            max_iterations=3,
        ).run("Submit the request")

        assert len(received) == 1
        assert len(received[0]) < 150
        compacted = [e for e in result.events if e.type == "model_output_compacted"]
        assert compacted[0].payload["removed_argument_fragments"] > 0

    def test_explicitly_requested_tool_gets_targeted_bounded_recovery(self) -> None:
        calls: list[str] = []

        def read_source(path: str) -> str:
            calls.append("read_source")
            return "buggy source"

        def apply_patch(path: str, patch: str) -> str:
            calls.append("apply_patch")
            return "patched"

        class StopsBeforeMutation:
            def __init__(self) -> None:
                self.turn = 0

            def complete(self, *, messages, **_kwargs):
                self.turn += 1
                if self.turn == 1:
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(name="read_source", arguments={"path": "a.py"})
                        ]
                    )
                if self.turn == 2:
                    return LLMResponse(content="The source needs a patch.")
                if self.turn == 3:
                    assert "`apply_patch`" in messages[-1].content
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(
                                name="apply_patch",
                                arguments={"path": "a.py", "patch": "fixed"},
                            )
                        ]
                    )
                return LLMResponse(content="Patched successfully.")

        result = Agent(
            llm=StopsBeforeMutation(),
            tools=[
                FunctionTool.from_callable(read_source, name="read_source"),
                FunctionTool.from_callable(apply_patch, name="apply_patch"),
            ],
            auto_use_skills=False,
            max_iterations=5,
        ).run("Use read_source, then apply_patch to fix a.py")

        assert calls == ["read_source", "apply_patch"]
        assert result.output == "Patched successfully."
        targeted = [
            event
            for event in result.events
            if event.type == "tool_call_healed"
            and event.payload.get("missing_tools") == ["apply_patch"]
        ]
        assert len(targeted) == 1


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


class TestWreckageIsNotHealed:
    """Healing rescues a call written as prose. It must not rescue one
    whose arguments are wreckage — that reaches the tool with the real
    parameter missing, and a tool with an optional filter then treats
    "no filter" as "everything"."""

    def _heal(self, arguments: str):
        from shipit_agent.tool_healing import heal_tool_calls

        text = f'<tool_call>{{"name":"search_echo","arguments":{arguments}}}</tool_call>'
        return heal_tool_calls(text, {"search_echo"})[1]

    def test_a_real_call_is_still_promoted(self) -> None:
        calls = self._heal('{"query":"qilin"}')
        assert calls and calls[0].arguments == {"query": "qilin"}

    def test_a_mangled_key_is_refused(self) -> None:
        """Observed from Gemma 4: the value survived, the key did not."""
        assert not self._heal('{"))Query:Qilin":"qilin"}')

    def test_pure_wreckage_is_refused(self) -> None:
        assert not self._heal('{":[{":","}')

    def test_the_text_is_left_alone_when_refused(self) -> None:
        from shipit_agent.tool_healing import heal_tool_calls

        text = '<tool_call>{"name":"search_echo","arguments":{":[{":","}}</tool_call>'
        remaining, calls = heal_tool_calls(text, {"search_echo"})
        assert not calls and remaining == text


#: ``search_echo`` as it should be declared — the shape an identifier regex
#: cannot reason about but a schema can.
SEARCH_SCHEMA = {
    "search_echo": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
}


class TestSchemaAwareHealing:
    """A name check asks "could this be a parameter?". A schema check asks
    "is this *the* parameter?" — which is the question that matters when a
    tool's filter is optional and a missing one means "return everything"."""

    def _heal(self, arguments: str, schemas=SEARCH_SCHEMA):
        from shipit_agent.tool_healing import heal_tool_calls

        text = f'<tool_call>{{"name":"search_echo","arguments":{arguments}}}</tool_call>'
        return heal_tool_calls(text, {"search_echo"}, schemas=schemas)[1]

    def test_the_declared_argument_is_promoted(self) -> None:
        calls = self._heal('{"query":"qilin"}')
        assert calls and calls[0].arguments == {"query": "qilin"}

    def test_a_misspelled_argument_is_refused(self) -> None:
        """``quary`` passes the identifier regex and fails the schema.

        This is the case the old guard could not see: a plausible-looking
        key that leaves the required parameter absent.
        """
        assert not self._heal('{"quary":"qilin"}')

    def test_a_missing_required_argument_is_refused(self) -> None:
        """The empty call is exactly the observed ``search_echo({})`` bug."""
        assert not self._heal("{}")

    def test_an_undeclared_extra_argument_does_not_block_a_valid_call(self) -> None:
        """Models add stray keys; that is not a reason to lose the call."""
        calls = self._heal('{"query":"qilin","limit":5}')
        assert calls and calls[0].arguments["query"] == "qilin"

    def test_without_a_schema_the_name_check_still_applies(self) -> None:
        """Unknown schema must not become "anything goes"."""
        assert self._heal('{"query":"qilin"}', schemas=None)
        assert not self._heal('{"))Query:Qilin":"qilin"}', schemas=None)


class TestNamelessArgumentObjects:
    """Onyx matches a bare arguments object to a tool by validating its keys
    against that tool's schema. Without this the call is simply lost."""

    def _heal(self, text: str):
        from shipit_agent.tool_healing import heal_tool_calls

        return heal_tool_calls(text, {"search_echo"}, schemas=SEARCH_SCHEMA)

    def test_a_bare_arguments_object_is_matched_to_its_tool(self) -> None:
        _, calls = self._heal('```json\n{"query":"qilin"}\n```')
        assert calls and calls[0].name == "search_echo"
        assert calls[0].arguments == {"query": "qilin"}

    def test_an_object_that_fits_no_tool_is_left_as_text(self) -> None:
        text = '```json\n{"unrelated":"value"}\n```'
        remaining, calls = self._heal(text)
        assert not calls and remaining == text

    def test_a_named_call_wins_over_schema_matching(self) -> None:
        _, calls = self._heal(
            '<tool_call>{"name":"search_echo","arguments":{"query":"a"}}</tool_call>'
        )
        assert len(calls) == 1 and calls[0].arguments == {"query": "a"}


class TestArgumentCoercion:
    """Observed model behaviour, not speculation: list-valued parameters
    arrive as JSON strings, and whole argument objects arrive double-encoded."""

    def _heal(self, arguments: str):
        from shipit_agent.tool_healing import heal_tool_calls

        schemas = {
            "web_search": {
                "type": "object",
                "properties": {"queries": {"type": "array"}},
                "required": ["queries"],
            }
        }
        text = f'<tool_call>{{"name":"web_search","arguments":{arguments}}}</tool_call>'
        return heal_tool_calls(text, {"web_search"}, schemas=schemas)[1]

    def test_a_json_string_list_becomes_a_list(self) -> None:
        calls = self._heal('{"queries":"[\\"a\\", \\"b\\"]"}')
        assert calls and calls[0].arguments["queries"] == ["a", "b"]

    def test_a_double_encoded_argument_object_is_unwrapped(self) -> None:
        calls = self._heal('"{\\"queries\\": [\\"a\\"]}"')
        assert calls and calls[0].arguments["queries"] == ["a"]

    def test_a_plain_string_value_is_left_alone(self) -> None:
        """Coercion must not mangle values that merely contain brackets."""
        calls = self._heal('{"queries":["a [not json]"]}')
        assert calls and calls[0].arguments["queries"] == ["a [not json]"]


class TestVarKwargsAreNotParameters:
    """``**kwargs`` has no default, so it was being advertised to the model
    as a *required* parameter — telling it to invent a value for
    ``**_ignored``, and making the declared ``required`` list useless for
    validating anything."""

    @staticmethod
    def _add(a: int, b: int, **_ignored: Any) -> str:
        return str(a + b)

    def _parameters(self) -> dict:
        from shipit_agent.tools import FunctionTool

        tool = FunctionTool.from_callable(self._add, name="add")
        return tool.schema()["function"]["parameters"]

    def test_var_kwargs_is_not_a_property(self) -> None:
        assert set(self._parameters()["properties"]) == {"a", "b"}

    def test_var_kwargs_is_not_required(self) -> None:
        assert self._parameters()["required"] == ["a", "b"]

    def test_the_real_arguments_now_validate(self) -> None:
        """The end the fix serves: healing can trust the declaration."""
        from shipit_agent.tool_healing import _arguments_fit_schema

        assert _arguments_fit_schema(
            {"a": 2, "b": 3}, self._parameters(), strict_required=True
        )
