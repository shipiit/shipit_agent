"""The one shared tool_choice ladder used by the OpenAI-shaped adapters."""
from shipit_agent.llms.tool_choice import resolve_tool_choice

_ONE = [{"function": {"name": "get_entity"}}]
_TWO = [{"function": {"name": "a"}}, {"function": {"name": "b"}}]


def test_single_required_tool_becomes_an_exact_function_choice():
    assert resolve_tool_choice(_ONE, require_tool_call=True) == {
        "type": "function", "function": {"name": "get_entity"}
    }


def test_several_required_tools_fall_back_to_required():
    assert resolve_tool_choice(_TWO, require_tool_call=True) == "required"


def test_no_tools_omits_the_parameter():
    assert resolve_tool_choice([], require_tool_call=True, default_auto=True) is None
    assert resolve_tool_choice(None, require_tool_call=False) is None


def test_configured_choice_wins_when_not_required():
    assert resolve_tool_choice(_TWO, configured="auto") == "auto"


def test_default_auto_only_applies_without_a_configured_choice():
    assert resolve_tool_choice(_TWO, default_auto=True) == "auto"
    assert resolve_tool_choice(_TWO) is None


def test_empty_function_name_does_not_produce_an_invalid_exact_choice():
    # A blank name would be an invalid exact choice; fall back to "required".
    assert resolve_tool_choice(
        [{"function": {"name": ""}}], require_tool_call=True
    ) == "required"
