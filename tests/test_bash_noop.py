"""A command that does nothing is refused, with a note the model can act on.

On a live run Gemma 4 called bash with `:` twice in one task, a full turn
each, apparently as a placeholder. Refusing it says what to do instead.
No command here reaches a real shell: the runner is a recorder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import shipit_agent.tools.bash.bash_tool as bash_module
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.bash.bash_tool import BashTool
from shipit_agent.tools.bash.runner import Finished


@pytest.fixture
def ran(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    commands: list[str] = []

    def record(command: str, *, cwd: Path, env: dict[str, str], timeout: float) -> Finished:
        commands.append(command)
        log = tmp_path / "log"
        log.write_text("")
        return Finished(0, "ok", "", 0.0, log, log)

    monkeypatch.setattr(bash_module, "run_command", record)
    return commands


@pytest.mark.parametrize("command", [":", " : ", "true", ":;", "true; :"])
def test_a_command_that_does_nothing_is_refused(command: str, ran: list[str], tmp_path: Path) -> None:
    out = BashTool(root_dir=tmp_path).run(ToolContext(prompt=""), command=command)
    assert out.text.startswith("Command rejected") and "does nothing" in out.text
    assert ran == []


@pytest.mark.parametrize("command", ["ls", ": > notes.txt", "true && ls", "python -c 'print(1)'"])
def test_real_commands_still_run(command: str, ran: list[str], tmp_path: Path) -> None:
    BashTool(root_dir=tmp_path).run(ToolContext(prompt=""), command=command)
    assert ran == [command]


def test_a_no_op_is_still_a_safe_command(tmp_path: Path) -> None:
    # The safety check answers "may this run?"; `:` may. ShipIt Cloud adds it
    # to its allowlist and checks exactly this. Only run() refuses it, as useless.
    BashTool(root_dir=tmp_path)._validate_command(":")
    BashTool(root_dir=tmp_path, allowed_command_prefixes=[":"])._validate_command(":")
