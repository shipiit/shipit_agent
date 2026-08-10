"""Where an instruction sits decides whether it is followed.

The same rule is obeyed far more reliably next to the tools it governs than
a few paragraphs earlier under a general heading. These rules used to live
in the base agent prompt, and the depth rule was being ignored: given
fifteen search hits and a request for detail, the model opened one and
answered from it.

So the placement is a contract, not a formatting preference.
"""

from __future__ import annotations

from shipit_agent import DEFAULT_AGENT_PROMPT
from shipit_agent.tools import FunctionTool
from shipit_agent.tools.helpers import build_tools_prompt

DEPTH_RULE = "A search is the beginning of the work"
BATCH_RULE = "Call several tools in ONE response"
EMPTY_ARGS_RULE = "Ask for what you need, not for everything"


def _tool(name: str = "search_echo"):
    def _fn(query: str) -> str:
        """Search the echo feed."""
        return query

    return FunctionTool.from_callable(_fn, name=name)


class TestTheRulesLiveWithTheTools:
    def test_the_depth_rule_is_in_the_tool_section(self) -> None:
        assert DEPTH_RULE in build_tools_prompt([_tool()])

    def test_the_depth_rule_is_not_in_the_base_prompt(self) -> None:
        """If it is in both, the near copy is competing with a far one."""
        assert DEPTH_RULE not in DEFAULT_AGENT_PROMPT

    def test_the_batching_rule_moved_too(self) -> None:
        assert BATCH_RULE in build_tools_prompt([_tool()])
        assert BATCH_RULE not in DEFAULT_AGENT_PROMPT

    def test_the_empty_arguments_rule_is_present(self) -> None:
        """The observed failure: a no-argument call returning a whole corpus."""
        assert EMPTY_ARGS_RULE in build_tools_prompt([_tool()])


class TestGatedOnHavingTools:
    def test_no_tools_means_no_tool_instructions(self) -> None:
        """A model with no tools must not be told how to call them."""
        assert build_tools_prompt([]) == ""

    def test_the_section_is_headed(self) -> None:
        prompt = build_tools_prompt([_tool()])
        assert prompt.startswith("# Tools")

    def test_families_are_subheadings(self) -> None:
        """Coherent sections the model can attend to, not one flat list."""
        assert "\n## " in build_tools_prompt([_tool()])


class TestTheToolListingSurvives:
    def test_each_tool_is_still_named(self) -> None:
        assert "- search_echo [" in build_tools_prompt([_tool("search_echo")])

    def test_the_description_is_not_repeated_here(self) -> None:
        """It is already in the JSON schema the provider requires, and that
        copy is the one the model selects on. Measured on a 43-tool agent, the
        second copy was ~3,800 tokens re-sent on every step of every turn."""
        assert "Search the echo feed." not in build_tools_prompt([_tool()])

    def test_what_the_schema_cannot_carry_is_kept(self) -> None:
        """Family, read-only status and origin have nowhere else to live."""
        prompt = build_tools_prompt([_tool()])
        assert "read-only" in prompt and "\n## " in prompt
