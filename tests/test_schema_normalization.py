"""A zero-argument tool must not take the whole request down with it.

JSON Schema does not require `properties`, so a tool that accepts nothing may
legally publish `{"type": "object"}` and stop — and MCP servers do exactly
that. OpenAI-compatible endpoints reject it: "object schema missing
properties".

The rejection is of the *request*, not of one tool. So the symptom is not a
single tool misbehaving; it is an agent that calls nothing at all, on every
turn, with no obvious cause — which is precisely how it was reported.
"""

from __future__ import annotations

from shipit_agent.construction import construct_tool_registry
from shipit_agent.registry import normalize_tool_schema
from shipit_agent.tools.base import ToolOutput


def _tool(parameters):
    class T:
        name = "list_regions"
        description = "List available regions"
        prompt_instructions = ""

        def schema(self):
            return {
                "type": "function",
                "function": {
                    "name": "list_regions",
                    "description": "List available regions",
                    "parameters": parameters,
                },
            }

        def run(self, context, **kwargs):
            return ToolOutput(text="ok")

    return T()


def _emitted(parameters):
    registry = construct_tool_registry(tools=[_tool(parameters)], mcps=[])
    return registry.schemas()[0]["function"]["parameters"]


class TestTheMissingKeyIsSupplied:
    def test_a_bare_object_gains_empty_properties(self) -> None:
        assert _emitted({"type": "object"}) == {"type": "object", "properties": {}}

    def test_it_applies_where_every_schema_passes_through(self) -> None:
        """One rule, so local tools and MCP tools are both covered."""
        assert "properties" in _emitted({"type": "object"})

    def test_an_absent_type_is_treated_as_an_object(self) -> None:
        """`type` defaults to object in JSON Schema, and providers assume it."""
        assert _emitted({}) == {"type": "object", "properties": {}}


class TestNothingElseIsRewritten:
    """This normalises one known incompatibility. It is not licence to edit
    tool declarations."""

    def test_declared_properties_are_untouched(self) -> None:
        parameters = {
            "type": "object",
            "properties": {"region": {"type": "string"}},
            "required": ["region"],
        }
        assert _emitted(parameters) == parameters

    def test_an_empty_properties_block_is_left_as_it_is(self) -> None:
        parameters = {"type": "object", "properties": {}}
        assert _emitted(parameters) == parameters

    def test_a_non_object_parameter_block_is_untouched(self) -> None:
        assert _emitted({"type": "string"}) == {"type": "string"}

    def test_required_and_extras_survive_the_patch(self) -> None:
        out = _emitted({"type": "object", "required": [], "title": "Regions"})
        assert out["title"] == "Regions" and out["required"] == []
        assert out["properties"] == {}


class TestTheHelperIsSafeOnAnything:
    def test_a_flat_schema_without_the_function_wrapper(self) -> None:
        out = normalize_tool_schema({"name": "x", "parameters": {"type": "object"}})
        assert out["parameters"]["properties"] == {}

    def test_a_schema_with_no_parameters_at_all(self) -> None:
        assert normalize_tool_schema({"name": "x"}) == {"name": "x"}

    def test_a_non_dict_is_returned_unchanged(self) -> None:
        assert normalize_tool_schema("not a schema") == "not a schema"

    def test_the_input_is_not_mutated(self) -> None:
        """Tools hand out their own dicts; patching in place would corrupt
        the tool's declaration for every later call."""
        original = {"type": "function",
                    "function": {"name": "x", "parameters": {"type": "object"}}}
        normalize_tool_schema(original)
        assert "properties" not in original["function"]["parameters"]
