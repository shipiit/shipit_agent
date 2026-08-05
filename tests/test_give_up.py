"""``give_up`` — a declared stop, not prose the loop has to guess at."""

from __future__ import annotations

from shipit_agent.narrate import summarize
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.contracts import contract_for
from shipit_agent.tools.give_up import GiveUpTool


def run(**kwargs):
    return GiveUpTool().run(ToolContext(prompt="x"), **kwargs)


class TestTool:
    def test_reason_is_reported(self) -> None:
        out = run(reason="No AWS credentials in the environment.")
        assert "No AWS credentials" in out.text
        assert out.metadata["gave_up"] is True
        assert out.metadata["give_up_reason"] == "No AWS credentials in the environment."

    def test_needs_are_listed(self) -> None:
        out = run(reason="Missing credentials", needs=["AWS_ACCESS_KEY_ID", "region"])
        assert "AWS_ACCESS_KEY_ID" in out.text and "region" in out.text
        assert out.metadata["give_up_needs"] == ["AWS_ACCESS_KEY_ID", "region"]

    def test_an_empty_reason_is_refused_rather_than_recorded(self) -> None:
        out = run(reason="")
        assert out.metadata["gave_up"] is False
        assert out.metadata["error"] == "missing_reason"
        assert "needs a reason" in out.text

    def test_whitespace_only_reason_is_refused(self) -> None:
        assert run(reason="   \n ").metadata["gave_up"] is False

    def test_missing_reason_argument_is_refused(self) -> None:
        assert run().metadata["gave_up"] is False

    def test_blank_needs_are_dropped(self) -> None:
        out = run(reason="stuck", needs=["", "  ", "a token"])
        assert out.metadata["give_up_needs"] == ["a token"]

    def test_the_stop_persists_to_memory(self) -> None:
        assert run(reason="stuck").metadata["persist"] is True

    def test_schema_requires_a_reason(self) -> None:
        schema = GiveUpTool().schema()["function"]["parameters"]
        assert schema["required"] == ["reason"]

    def test_prompt_discourages_premature_use(self) -> None:
        instructions = GiveUpTool().prompt_instructions.lower()
        assert "not" in instructions and "tried" in instructions


class TestWiring:
    def test_registered_as_a_builtin(self) -> None:
        from shipit_agent.builtins import get_builtin_tools

        names = {getattr(t, "name", "") for t in get_builtin_tools(llm=None, project_root=".")}
        assert "give_up" in names

    def test_it_is_an_observation(self) -> None:
        # Gating "I'm blocked" would only stop the agent telling you so.
        assert contract_for("give_up").read_only

    def test_it_narrates(self) -> None:
        assert summarize("give_up", {"reason": "No credentials"}).past_label() == (
            "Stopped No credentials"
        )


class TestRuntimeSurfacing:
    def test_a_stop_reaches_agent_result_metadata(self) -> None:
        from shipit_agent import Agent
        from shipit_agent.llms.base import LLMResponse
        from shipit_agent.models import ToolCall

        class L:
            model = "t"

            def __init__(self):
                self.n = 0

            def complete(self, *, messages, tools=None, system_prompt=None,
                         metadata=None, text_delta_callback=None):
                script = [
                    ("", [("give_up", {"reason": "No AWS credentials",
                                       "needs": ["AWS_ACCESS_KEY_ID"]})]),
                    ("I can't deploy without credentials.", []),
                ]
                step = script[self.n] if self.n < len(script) else ("", [])
                self.n += 1
                return LLMResponse(
                    content=step[0],
                    tool_calls=[ToolCall(name=n, arguments=a) for n, a in step[1]],
                )

        result = Agent(
            llm=L(), tools=[GiveUpTool()], auto_use_skills=False, max_iterations=3
        ).run("Deploy to prod")

        assert result.metadata["gave_up"] is True
        assert result.metadata["give_up_reason"] == "No AWS credentials"
        assert result.metadata["give_up_needs"] == ["AWS_ACCESS_KEY_ID"]

    def test_a_normal_run_is_not_marked(self) -> None:
        from shipit_agent import Agent
        from shipit_agent.llms.base import LLMResponse

        class L:
            model = "t"

            def complete(self, **_):
                return LLMResponse(content="All done.")

        result = Agent(llm=L(), auto_use_skills=False).run("hi")
        assert "gave_up" not in result.metadata
