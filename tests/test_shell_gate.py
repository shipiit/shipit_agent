"""The shell runs any command; risky ones need approval, a few never run.

An agent with no permission settings runs everyday commands freely. A risky
command (deleting, publishing, writing outside the project...) runs only
with an allow rule, bypass mode, or a yes from ``permission_callback``;
otherwise it is not run and the model is told why. Blocked commands never
run, whatever the settings.

No test here hands a destructive command to a real shell: the command
runner is replaced by a recorder, so a gate that failed would show up as a
recorded command, not as deleted files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import shipit_agent.tools.bash.bash_tool as bash_module
from shipit_agent import Agent
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.safety.permissions import PermissionDecision, PermissionResult
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.bash.bash_tool import BashTool
from shipit_agent.tools.bash.runner import Finished


@pytest.fixture
def ran(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """Commands that reached the shell; none is actually executed."""
    commands: list[str] = []

    def record(
        command: str, *, cwd: Path, env: dict[str, str], timeout: float, argv: list[str] | None = None
    ) -> Finished:
        commands.append(command)
        log = tmp_path / f"log{len(commands)}"
        log.write_text("")
        return Finished(0, "ran", "", 0.0, log, log)

    monkeypatch.setattr(bash_module, "run_command", record)
    return commands


class _RunsOnce:
    def __init__(self, command: str) -> None:
        self.command = command
        self.turn = 0

    def complete(self, **_: Any) -> LLMResponse:
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name="bash", arguments={"command": self.command})],
            )
        return LLMResponse(content="done")


def _run(tmp_path: Path, command: str, **options: Any) -> Any:
    agent = Agent(
        llm=_RunsOnce(command), tools=[BashTool(root_dir=tmp_path)], **options
    )
    return agent.run("go")


def _tool_message(result: Any) -> str:
    return next(m.content for m in result.messages if m.role == "tool")


def test_an_everyday_command_runs_without_settings(
    tmp_path: Path, ran: list[str]
) -> None:
    _run(tmp_path, "seq 1 3 > nums.txt && cat nums.txt")
    assert ran == ["seq 1 3 > nums.txt && cat nums.txt"]


def test_a_risky_command_needs_approval_and_does_not_run(
    tmp_path: Path, ran: list[str]
) -> None:
    result = _run(tmp_path, "rm keep.txt")
    assert ran == []
    message = _tool_message(result)
    assert "requires" in message and "deletes files" in message


def test_a_yes_from_the_callback_runs_it(tmp_path: Path, ran: list[str]) -> None:
    asked: list[dict[str, Any]] = []

    def approve(name: str, arguments: dict[str, Any]) -> PermissionResult:
        asked.append(arguments)
        return PermissionResult(PermissionDecision.ALLOW, reason="user said yes")

    _run(tmp_path, "rm keep.txt", permission_callback=approve)
    assert ran == ["rm keep.txt"]
    assert asked == [{"command": "rm keep.txt"}]


def test_a_no_from_the_callback_keeps_it_from_running(
    tmp_path: Path, ran: list[str]
) -> None:
    def refuse(name: str, arguments: dict[str, Any]) -> PermissionResult:
        return PermissionResult(PermissionDecision.DENY, reason="not today")

    result = _run(tmp_path, "rm keep.txt", permission_callback=refuse)
    assert ran == []
    assert "not today" in _tool_message(result)


def test_a_callback_with_no_opinion_leaves_it_unapproved(
    tmp_path: Path, ran: list[str]
) -> None:
    result = _run(
        tmp_path, "rm keep.txt", permission_callback=lambda name, arguments: None
    )
    assert ran == []
    assert "requires" in _tool_message(result)


def test_an_allow_rule_runs_risky_commands(tmp_path: Path, ran: list[str]) -> None:
    _run(tmp_path, "rm keep.txt", permissions={"allow": ["bash"]})
    assert ran == ["rm keep.txt"]


def test_bypass_mode_runs_risky_commands(tmp_path: Path, ran: list[str]) -> None:
    _run(tmp_path, "rm keep.txt", permission_mode="bypass")
    assert ran == ["rm keep.txt"]


@pytest.mark.parametrize(
    "options", [{}, {"permission_mode": "bypass"}, {"permissions": {"allow": ["bash"]}}]
)
def test_a_blocked_command_never_runs(
    tmp_path: Path, ran: list[str], options: dict[str, Any]
) -> None:
    result = _run(tmp_path, "rm -rf ~", **options)
    assert ran == []
    assert "blocked" in _tool_message(result)


def test_the_tool_itself_never_runs_a_blocked_command(
    tmp_path: Path, ran: list[str]
) -> None:
    out = BashTool(root_dir=tmp_path).run(ToolContext(prompt="t"), command="rm -rf ~")
    assert ran == []
    assert out.metadata["error"] == "invalid_command"
    assert "blocked" in out.text


@pytest.mark.parametrize("command", ["git reset --hard", "rm -rf /tmp/scratch-build"])
def test_approved_risky_commands_are_not_refused_by_the_tool(
    tmp_path: Path, ran: list[str], command: str
) -> None:
    out = BashTool(root_dir=tmp_path).run(ToolContext(prompt="t"), command=command)
    assert ran == [command], out.text


def test_explicit_blocked_substrings_apply_in_the_full_shell(
    tmp_path: Path, ran: list[str]
) -> None:
    tool = BashTool(root_dir=tmp_path, blocked_substrings=["docker"])
    out = tool.run(ToolContext(prompt="t"), command="docker ps")
    assert ran == []
    assert out.metadata["error"] == "invalid_command"
