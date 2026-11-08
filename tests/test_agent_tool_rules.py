"""``allowed_tools``, ``disallowed_tools`` and ``max_turns`` on the Agent,
as the Claude Agent SDK defines them.

- A bare name in ``disallowed_tools`` removes the tool: the model never sees it.
- A scoped entry (``Bash(rm *)``) keeps the tool and denies matching calls,
  in every permission mode.
- ``allowed_tools`` pre-approves; it does not restrict the other tools.

No command here reaches a real shell: the runner is replaced by a recorder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import shipit_agent.tools.bash.bash_tool as bash_module
from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.tools.bash.bash_tool import BashTool
from shipit_agent.tools.bash.runner import Finished


@pytest.fixture
def ran(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
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


class _Calls:
    """Makes the given calls, one per step, then answers; records the tools offered."""

    def __init__(self, *calls: tuple[str, dict[str, Any]]) -> None:
        self.calls = list(calls)
        self.offered: list[list[str]] = []

    def complete(self, *, tools: Any = None, **_: Any) -> LLMResponse:
        self.offered.append(sorted(t["function"]["name"] for t in tools or []))
        if self.calls:
            name, arguments = self.calls.pop(0)
            return LLMResponse(content="", tool_calls=[ToolCall(name=name, arguments=arguments)])
        return LLMResponse(content="done")


def _echo(text: str = "") -> str:
    """Echo the text."""
    return f"echo:{text}"


def _note(text: str = "") -> str:
    """Write a note."""
    return f"noted:{text}"


ECHO = FunctionTool.from_callable(_echo, name="echo")
NOTE = FunctionTool.from_callable(_note, name="note_create")


def _tool_messages(result: Any) -> list[str]:
    return [str(r.output) for r in result.tool_results]


def test_a_bare_disallowed_tool_is_never_offered() -> None:
    llm = _Calls()
    Agent(llm=llm, tools=[ECHO, NOTE], disallowed_tools=["note_create"]).run("go")
    assert "note_create" not in llm.offered[0]
    assert "echo" in llm.offered[0]


def test_a_removed_tool_cannot_be_called_anyway() -> None:
    llm = _Calls(("note_create", {"text": "x"}))
    result = Agent(llm=llm, tools=[ECHO, NOTE], disallowed_tools=["note_create"]).run("go")
    assert not any(message.startswith("noted:") for message in _tool_messages(result))


def test_a_glob_removes_every_matching_tool() -> None:
    mcp_like = FunctionTool.from_callable(_echo, name="mcp__srv__echo")
    llm = _Calls()
    Agent(llm=llm, tools=[ECHO, mcp_like], disallowed_tools=["mcp__*"]).run("go")
    assert "mcp__srv__echo" not in llm.offered[0]
    assert "echo" in llm.offered[0]


def test_a_scoped_disallowed_rule_keeps_the_tool_and_denies_matching_calls(
    ran: list[str], tmp_path: Path
) -> None:
    llm = _Calls(("bash", {"command": "rm -rf build"}), ("bash", {"command": "ls"}))
    Agent(
        llm=llm,
        tools=[BashTool(root_dir=tmp_path)],
        permission_mode="bypassPermissions",
        disallowed_tools=["Bash(rm *)"],
        project_root=tmp_path,
    ).run("go")
    assert "bash" in llm.offered[0]
    assert ran == ["ls"]


def test_allowed_tools_pre_approve_in_dont_ask_mode() -> None:
    llm = _Calls(("echo", {"text": "a"}), ("note_create", {"text": "b"}))
    result = Agent(
        llm=llm,
        tools=[ECHO, NOTE],
        allowed_tools=["echo"],
        permission_mode="dontAsk",
    ).run("go")
    messages = _tool_messages(result)
    assert "echo:a" in messages
    assert "noted:b" not in messages


def test_allowed_tools_do_not_restrict_the_other_tools() -> None:
    llm = _Calls(("note_create", {"text": "b"}))
    result = Agent(llm=llm, tools=[ECHO, NOTE], allowed_tools=["echo"]).run("go")
    assert "noted:b" in _tool_messages(result)


def test_a_user_engine_gets_the_rules_once_across_runs() -> None:
    from shipit_agent.safety.permissions import PermissionEngine

    engine = PermissionEngine(deny=["sql"])
    agent = Agent(llm=_Calls(), tools=[ECHO], permissions=engine, disallowed_tools=["note_create"])
    agent.run("one")
    agent.run("two")
    assert engine.deny == ["sql", "note_create"]


def test_max_turns_is_max_iterations() -> None:
    llm = _Calls(*[("echo", {"text": str(i)}) for i in range(5)])
    result = Agent(llm=llm, tools=[ECHO], max_turns=2).run("go")
    assert result.subtype == "error_max_turns"
    assert len(result.tool_results) == 2


def test_max_turns_and_a_different_max_iterations_conflict() -> None:
    with pytest.raises(ValueError, match="max_turns"):
        Agent(llm=_Calls(), max_turns=2, max_iterations=3)


@pytest.mark.parametrize("value", [0, -1, "3", 2.5])
def test_max_turns_must_be_a_positive_integer(value: Any) -> None:
    with pytest.raises(ValueError):
        Agent(llm=_Calls(), max_turns=value)


def test_the_rules_survive_a_json_round_trip_of_the_settings() -> None:
    agent = Agent(llm=_Calls(), allowed_tools=["Read"], disallowed_tools=["Bash(rm *)"])
    assert json.loads(json.dumps(agent.disallowed_tools)) == ["Bash(rm *)"]
