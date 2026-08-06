"""A missing argument is something the model can fix, not a crash."""

from __future__ import annotations

import pytest

from shipit_agent.models import ToolCall
from shipit_agent.registry import ToolRegistry
from shipit_agent.tool_runner import ToolRunner
from shipit_agent.tools.base import ToolContext, ToolOutput


def strict_tool(name="run_code"):
    """The shape 10+ shipped tools use: bare kwargs[...] lookups."""

    class T:
        def __init__(self):
            self.name = name
            self.description = name
            self.prompt_instructions = ""

        def schema(self):
            return {"function": {"name": name, "parameters": {
                "type": "object",
                "properties": {"language": {"type": "string"},
                               "code": {"type": "string"}},
                "required": ["language", "code"]}}}

        def run(self, context, **kwargs):
            language = str(kwargs["language"])
            return ToolOutput(text=f"ran {language}")

    return T()


def typed_tool():
    class T:
        name = "typed"
        description = "t"
        prompt_instructions = ""

        def schema(self):
            return {"function": {"name": "typed", "parameters": {
                "properties": {"path": {"type": "string"}},
                "required": ["path"]}}}

        def run(self, context, *, path):
            return ToolOutput(text=path)

    return T()


def run(tool, **arguments):
    runner = ToolRunner(ToolRegistry.build(tools=[tool]))
    return runner.run_tool_call(
        ToolCall(name=tool.name, arguments=arguments), ToolContext(prompt="x")
    )


class TestMissingArguments:
    def test_a_bare_key_lookup_becomes_a_usable_error(self) -> None:
        result = run(strict_tool(), code="print(1)")
        assert result.metadata["error"] == "missing_argument"
        assert result.metadata["argument"] == "language"
        assert "needs the 'language' argument" in result.output

    def test_a_typed_signature_becomes_the_same_error(self) -> None:
        result = run(typed_tool())
        assert result.metadata["error"] == "missing_argument"
        assert result.metadata["argument"] == "path"

    def test_the_message_lists_what_the_tool_requires(self) -> None:
        # So the next turn can supply everything, not discover them one at a
        # time over three round trips.
        assert "Required: language, code" in run(strict_tool(), code="x").output

    def test_a_correct_call_is_unaffected(self) -> None:
        result = run(strict_tool(), language="python", code="print(1)")
        assert result.output == "ran python"
        assert "error" not in result.metadata

    def test_it_does_not_raise(self) -> None:
        # Raising means the retry policy retries an identical call that fails
        # identically, burning the iteration budget on nothing.
        run(strict_tool(), code="x")


class TestItDoesNotHideRealBugs:
    def test_a_tools_own_key_error_still_raises(self) -> None:
        """A tool with a genuine bug must not be relabelled as the model's.

        The distinguishing test is whether the missing key is a parameter the
        tool *declares*. An internal dict lookup names something the caller
        was never asked for.
        """

        class Buggy:
            name = "buggy"
            description = "b"
            prompt_instructions = ""

            def schema(self):
                return {"function": {"name": "buggy", "parameters": {}}}

            def run(self, context, **kwargs):
                return {"a": 1}["missing_internal_key"]

        with pytest.raises(KeyError):
            run(Buggy())

    def test_an_argument_that_was_supplied_still_raises(self) -> None:
        class Odd:
            name = "odd"
            description = "o"
            prompt_instructions = ""

            def schema(self):
                return {"function": {"name": "odd", "parameters": {}}}

            def run(self, context, **kwargs):
                raise KeyError("path")  # but `path` *was* given

        with pytest.raises(KeyError):
            run(Odd(), path="a.py")

    def test_an_unrelated_type_error_still_raises(self) -> None:
        class Broken:
            name = "broken"
            description = "b"
            prompt_instructions = ""

            def schema(self):
                return {"function": {"name": "broken", "parameters": {}}}

            def run(self, context, **kwargs):
                return 1 + "not a number"

        with pytest.raises(TypeError):
            run(Broken())


class TestTheOriginalReport:
    def test_code_execution_no_longer_crashes_on_a_missing_language(self) -> None:
        """The bug that started this, on the real tool."""
        from shipit_agent.tools.code_execution import CodeExecutionTool

        result = run(CodeExecutionTool(), code="print(1)")
        assert result.metadata["error"] == "missing_argument"
        assert result.metadata["argument"] == "language"

    @pytest.mark.parametrize("name,arguments", [
        ("web_search", {}),
        ("grep_files", {}),
        ("glob_files", {}),
        ("plan_task", {}),
        ("open_url", {}),
    ])
    def test_every_tool_with_this_shape_is_covered(self, name, arguments) -> None:
        from shipit_agent.builtins import get_builtin_tool_map

        tool = get_builtin_tool_map(llm=None, project_root=".")[name]
        result = run(tool, **arguments)
        assert result.metadata.get("error") == "missing_argument", name
