"""Security regression tests for BashTool._validate_command (SEC-1).

The allowlist historically only inspected the first token of each shell
segment, so command substitution / process substitution / redirection ran
arbitrary, non-allowlisted commands. These tests pin the now-rejected
bypasses and confirm legitimate allowlisted commands still pass.
"""

from __future__ import annotations

import pytest

from shipit_agent.tools.bash.bash_tool import BashTool


@pytest.fixture()
def tool(tmp_path) -> BashTool:
    return BashTool(root_dir=tmp_path)


class TestBypassesRejected:
    def test_command_substitution_dollar_paren(self, tool: BashTool) -> None:
        with pytest.raises(ValueError):
            tool._validate_command("echo RESULT=$(id -un)")

    def test_command_substitution_backticks(self, tool: BashTool) -> None:
        with pytest.raises(ValueError):
            tool._validate_command("echo `id`")

    def test_process_substitution_input(self, tool: BashTool) -> None:
        with pytest.raises(ValueError):
            tool._validate_command("cat <(id)")

    def test_process_substitution_output(self, tool: BashTool) -> None:
        with pytest.raises(ValueError):
            tool._validate_command("tee >(cat) < /dev/null")

    def test_redirect_overwrite(self, tool: BashTool) -> None:
        with pytest.raises(ValueError):
            tool._validate_command("echo hi > /etc/passwd")

    def test_redirect_append(self, tool: BashTool) -> None:
        with pytest.raises(ValueError):
            tool._validate_command("echo hi >> /tmp/x")

    def test_redirect_input(self, tool: BashTool) -> None:
        with pytest.raises(ValueError):
            tool._validate_command("cat < /etc/passwd")

    def test_non_allowlisted_first_token_still_rejected(self, tool: BashTool) -> None:
        with pytest.raises(ValueError):
            tool._validate_command("id")

    def test_unclosed_quote_is_rejected_as_invalid_syntax(self, tool: BashTool) -> None:
        with pytest.raises(ValueError, match="Invalid shell syntax"):
            tool._validate_command("pytest -q 'unterminated")


class TestLegitimateCommandsPass:
    def test_plain_echo(self, tool: BashTool) -> None:
        tool._validate_command("echo hello")

    def test_pipeline_of_allowlisted(self, tool: BashTool) -> None:
        tool._validate_command("cat foo.txt | grep bar | wc -l")

    def test_pipe_inside_quoted_regex_is_not_a_shell_separator(
        self, tool: BashTool
    ) -> None:
        tool._validate_command('grep -rnE "retry|HTTPStatus" .')

    def test_chained_allowlisted(self, tool: BashTool) -> None:
        tool._validate_command("ls && pwd")

    def test_git_status(self, tool: BashTool) -> None:
        tool._validate_command("git status")

    def test_pytest_run(self, tool: BashTool) -> None:
        tool._validate_command("pytest -q tests/")

    def test_run_returns_recoverable_error_for_invalid_syntax(
        self, tool: BashTool
    ) -> None:
        from shipit_agent.models import ToolCall
        from shipit_agent.registry import ToolRegistry
        from shipit_agent.tool_runner import ToolRunner
        from shipit_agent.tools.base import ToolContext

        output = ToolRunner(ToolRegistry.build(tools=[tool])).run_tool_call(
            ToolCall(
                name="bash", arguments={"command": "pytest -q 'unterminated"}
            ),
            ToolContext(prompt="test"),
        )
        assert output.metadata["error"] == "invalid_arguments"
        assert "No closing quotation" in output.output
